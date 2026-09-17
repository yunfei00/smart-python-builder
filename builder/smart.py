from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from analyzer import ProjectAnalysis, analyze_project

from .engine import BuildEngine, BuildRequest, BuildResult
from .experience import ExperienceEngine
from .models import BuildPlan
from .ai import RepairPlan, configured_provider
from .notifications import NotificationService
from .learning import ExperienceStore
from .settings import SettingsStore


@dataclass(slots=True)
class SmartBuildResult:
    analysis: ProjectAnalysis
    build: BuildResult
    plan: BuildPlan
    status: str = "SUCCESS"
    attempts: list[dict] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    candidate_id: str | None = None


class EntryPointRequired(ValueError):
    def __init__(self, analysis: ProjectAnalysis):
        self.analysis = analysis
        candidates = ", ".join(str(p.relative_to(analysis.project_root)) for p in analysis.entry_candidates)
        detail = candidates or "no conventional entry candidates"
        super().__init__(f"Entry point must be selected: {detail}")


class SmartBuilder:
    """Analyze an uploaded source and feed deterministic results into BuildEngine."""

    def __init__(self, workspace_root: Path | str = "workspace", timeout: int = 900, *, ai_provider=None, artifact_validator=None, notifications=None, experience_store=None, settings_store=None):
        settings = (settings_store or SettingsStore('web-data/settings.sqlite3')).effective()
        self.engine = BuildEngine(workspace_root, timeout)
        self.experiences = ExperienceEngine()
        self.ai_provider = ai_provider if ai_provider is not None else configured_provider(settings)
        self.artifact_validator = artifact_validator
        self.on_state = None
        self.notifications = notifications or NotificationService.configured(settings)
        self.details_url = settings['base_url']
        self.experience_store = experience_store or ExperienceStore(self.engine.workspace_root / 'experiences.sqlite3')
        self.experiences.store = self.experience_store

    def build(
        self,
        source: Path | str,
        *,
        entry_point: Path | str | None = None,
        windowed: bool | None = None,
        app_name: str | None = None,
        mode: str = "onefile",
        plan: BuildPlan | None = None,
    ) -> SmartBuildResult:
        analysis = analyze_project(source)
        selected_entry = self._select_entry(analysis, entry_point)
        plan = plan or self.experiences.plan(analysis, selected_entry, windowed=windowed, mode=mode)
        plan.validate(analysis.project_root)
        if (analysis.project_root / plan.entry_point).resolve() != selected_entry:
            raise ValueError('Build Plan entry differs from selected entry')
        attempts, states = [], []
        def transition(state):
            states.append(state)
            if self.on_state:
                self.on_state(state)
        transition('BUILDING')
        for attempt in range(3):
            result = self.engine.build(BuildRequest(
                source=analysis.source,
                packages=plan.dependencies,
                windowed=windowed,
                app_name=app_name,
                entry_point=selected_entry,
                plan=plan,
            ))
            # Optional internal smoke validator is code supplied by the operator,
            # never a command or callback from an AI response.
            if result.success and self.artifact_validator:
                try:
                    self.artifact_validator(result.artifact)
                except Exception as exc:
                    result.success, result.error = False, str(exc)
                    with result.log_file.open('a', encoding='utf-8') as log:
                        log.write('\nArtifact validation failed: ' + str(exc))
            attempts.append(dict(number=attempt+1, build_id=result.build_id, success=result.success, error=result.error, plan=plan.to_dict()))
            if result.success:
                transition('SUCCESS')
                break
            transition('FAILED')
            if attempt == 0:
                self.notifications.emit(dict(event='Build Failed', build_id=result.build_id, project=analysis.source.name,
                    entry=plan.entry_point, dependencies=plan.dependencies, failed_stage='build/artifact validation',
                    error_summary=result.error, ai_diagnosis_started=self.ai_provider is not None, details_url=self.details_url))
            if self.ai_provider is None:
                break
            if attempt == 2:
                transition('NEEDS_MANUAL_REVIEW')
                break
            transition('AI_DIAGNOSING')
            try:
                context = dict(project_structure=[str(p.relative_to(analysis.project_root)) for p in analysis.project_root.rglob('*') if p.is_file()][:2000],
                               static_analysis=dict(imports=sorted(analysis.imports), internal=sorted(analysis.internal_imports)),
                               dependencies=plan.dependencies, matched_experiences=plan.matched_experiences,
                               build_plan=plan.to_dict(), pyinstaller_log=result.log_file.read_text(encoding='utf-8', errors='replace')[-80000:],
                               error=result.error, previous_attempts=attempts)
                repair = RepairPlan.model_validate(self.ai_provider.diagnose(context))
                attempts[-1]['repair'] = repair.model_dump()
                if not repair.retry:
                    transition('NEEDS_MANUAL_REVIEW')
                    break
                transition('AI_REPAIRING')
                plan = repair.apply(plan, analysis.project_root)
                transition('REBUILDING')
            except Exception as exc:
                attempts[-1]['diagnosis_error'] = str(exc)
                transition('NEEDS_MANUAL_REVIEW')
                break
        candidate_id = None
        if result.success and len(attempts) > 1:
            candidate_id = self.experience_store.candidate(analysis, attempts, plan)
        if any('repair' in item or 'diagnosis_error' in item for item in attempts):
            self.notifications.emit(dict(event='AI Repair Success' if result.success else 'AI Repair Failed',
                build_id=result.build_id, original_error=attempts[0]['error'], final_error=result.error,
                attempts=[dict(number=item['number'], success=item['success']) for item in attempts],
                diagnoses=[item.get('repair', item.get('diagnosis_error')) for item in attempts if 'repair' in item or 'diagnosis_error' in item],
                status=states[-1], experience_candidate=candidate_id,
                details_url=self.details_url, approval_url=self.details_url.split('?')[0].rstrip('/')+'/admin'))
        (result.workspace / 'attempts.json').write_text(json.dumps(dict(states=states, attempts=attempts, notification_failures=self.notifications.failures), ensure_ascii=False, indent=2), encoding='utf-8')
        return SmartBuildResult(analysis, result, plan, states[-1], attempts, states, candidate_id)

    @staticmethod
    def _select_entry(analysis: ProjectAnalysis, entry_point: Path | str | None) -> Path:
        if entry_point is None:
            if analysis.entry_point is None:
                raise EntryPointRequired(analysis)
            return analysis.entry_point

        candidate = Path(entry_point)
        if not candidate.is_absolute():
            candidate = analysis.project_root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(analysis.project_root)
        except ValueError as exc:
            raise ValueError("Selected entry point must be inside the project") from exc
        if candidate not in analysis.python_files:
            raise ValueError("Selected entry point is not an analyzed Python file")
        return candidate
