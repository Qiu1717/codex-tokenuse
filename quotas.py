"""读取当前账户额度；凭据仅通过 curl 标准输入发送给 ChatGPT。"""
import json
import subprocess
import urllib.request

from core import quota_summary


def fetch_quota(codex_home):
    auth = json.loads((codex_home / 'auth.json').read_text(encoding='utf-8')).get('tokens') or {}
    token, account = auth.get('access_token'), auth.get('account_id')
    if not token or not account:
        raise RuntimeError('Codex 登录状态不可用')
    headers = {'Authorization': 'Bearer ' + token, 'ChatGPT-Account-Id': account,
               'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Origin': 'https://chatgpt.com'}
    if any('\r' in value or '\n' in value for value in headers.values()):
        raise RuntimeError('登录信息格式无效')
    proxies = urllib.request.getproxies()
    proxy = proxies.get('https') or proxies.get('http')

    def request(endpoint):
        config = 'url = ' + json.dumps('https://chatgpt.com/backend-api/wham/' + endpoint) + '\n'
        config += ''.join('header = ' + json.dumps(key + ': ' + value) + '\n' for key, value in headers.items())
        if proxy:
            config += 'proxy = ' + json.dumps(proxy) + '\n'
        response = subprocess.run(['curl.exe', '-q', '--config', '-', '--silent', '--show-error', '--fail',
                                   '--proto', '=https', '--max-time', '15'],
                                  input=config, capture_output=True, text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=18)
        if response.returncode:
            raise RuntimeError('额度读取失败，请稍后刷新')
        return json.loads(response.stdout)

    data = request('usage')
    result = quota_summary(data)
    if result['reset_cards'] is None:
        try:
            details = request('rate-limit-reset-credits')
            result['reset_cards'] = quota_summary({'rate_limit_reset_credits': details})['reset_cards']
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
    return result
