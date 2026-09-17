"""Validated externally reachable Builder links; never infer a network address."""
import ipaddress
from urllib.parse import urlencode, urlsplit, urlunsplit


def normalize_base_url(value):
    value = value.strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or '?' in value or '#' in value or '\\' in value
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError()
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and address.is_unspecified:
            raise ValueError()
        if port == 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Builder 访问地址必须为 HTTP(S) 地址，不能含凭证、查询、片段或 0.0.0.0/:: 监听地址') from None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def local_base_url(value):
    host = urlsplit(value).hostname
    if host and host.rstrip('.').lower() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def builder_links(base_url, web_job_id=None):
    base = normalize_base_url(base_url)
    return {'details_url': base + ('/?' + urlencode({'job': web_job_id}) if web_job_id else '/'),
            'approval_url': base + '/admin'}
