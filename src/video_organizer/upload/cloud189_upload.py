#!/usr/bin/env python3
"""
天翼云盘上传工具 - Python 版本
基于 cloud189-sdk (Node.js) 实现
"""

import os
import re
import json
import time
import hashlib
import secrets
import requests
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

# 进度条
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
from urllib.parse import urlencode, quote, urlparse, parse_qs

# 尝试导入加密库
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("警告: cryptography 库未安装，请运行: pip install cryptography")


# ============== 常量定义 ==============
WEB_URL = 'https://cloud.189.cn'
AUTH_URL = 'https://open.e.189.cn'
API_URL = 'https://api.cloud.189.cn'
UPLOAD_URL = 'https://upload.cloud.189.cn'

AccountType = '02'
AppID = '8025431004'
ClientType = '10020'
ReturnURL = 'https://m.cloud.189.cn/zhuanti/2020/loginErrorPc/index.html'
UserAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36'


def client_suffix() -> Dict[str, Any]:
    return {
        'clientType': 'TELEPC',
        'version': '6.2',
        'channelId': 'web_cloud.189.cn',
        'rand': int(time.time() * 1000)
    }


# ============== 数据类 ==============
@dataclass
class UploadResult:
    """上传结果"""
    success: bool
    rapid_upload: bool = False
    user_file_id: Optional[str] = None
    file_name: Optional[str] = None
    file_size: int = 0
    file_md5: Optional[str] = None
    slice_md5: Optional[str] = None
    slice_md5s: List[str] = field(default_factory=list)
    message: str = ''


@dataclass
class TokenInfo:
    """Token 信息"""
    access_token: str = ''
    refresh_token: str = ''
    session_key: str = ''
    family_session_key: str = ''  # 家庭云专用 sessionKey
    family_session_secret: str = ''  # 家庭云专用 sessionSecret
    expires_in: int = 0
    expires_at: float = 0


# ============== 加密工具 ==============
class CryptoUtils:
    """加密工具类"""
    
    @staticmethod
    def md5(data: bytes | str) -> str:
        """计算 MD5"""
        if isinstance(data, str):
            data = data.encode('utf-8')
        return hashlib.md5(data).hexdigest()
    
    @staticmethod
    def _format_public_key(public_key: str) -> str:
        """格式化公钥为标准 PEM 格式"""
        # 移除已有的 PEM 标记和空白
        public_key = public_key.replace('-----BEGIN PUBLIC KEY-----', '')
        public_key = public_key.replace('-----END PUBLIC KEY-----', '')
        public_key = public_key.replace('\n', '').replace('\r', '').replace(' ', '').strip()
        
        # 直接使用 Node.js 的格式（不按 64 字符换行，让 cryptography 自动处理）
        return f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----"
    
    @staticmethod
    def rsa_encrypt(public_key: str, data: str) -> str:
        """RSA 加密 (PKCS1 padding)"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography 库未安装")
        
        # 格式化公钥
        pem_key = CryptoUtils._format_public_key(public_key)
        
        # 加载公钥
        pub_key = serialization.load_pem_public_key(
            pem_key.encode('utf-8'),
            backend=default_backend()
        )
        
        # RSA 加密
        encrypted = pub_key.encrypt(
            data.encode('utf-8'),
            padding.PKCS1v15()
        )
        return encrypted.hex()
    
    @staticmethod
    def rsa_encrypt_base64(public_key: str, data: str) -> str:
        """RSA 加密并返回 Base64"""
        import base64
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography 库未安装")
        
        pem_key = CryptoUtils._format_public_key(public_key)
        pub_key = serialization.load_pem_public_key(
            pem_key.encode('utf-8'),
            backend=default_backend()
        )
        encrypted = pub_key.encrypt(
            data.encode('utf-8'),
            padding.PKCS1v15()
        )
        return base64.b64encode(encrypted).decode('utf-8')
    
    @staticmethod
    def aes_ecb_encrypt(data: Dict[str, Any], key: str) -> str:
        """AES-128-ECB 加密"""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography 库未安装")
        
        # 构建参数字符串
        params = '&'.join(f'{k}={v}' for k, v in data.items())
        
        # AES 加密
        cipher = Cipher(
            algorithms.AES(key.encode('utf-8')),
            modes.ECB(),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        
        # PKCS7 padding
        block_size = 16
        padding_len = block_size - (len(params) % block_size)
        padded_data = params + chr(padding_len) * padding_len
        
        encrypted = encryptor.update(padded_data.encode('utf-8')) + encryptor.finalize()
        return encrypted.hex()
    
    @staticmethod
    def hmac_sha1(data: Dict[str, Any], key: str) -> str:
        """HMAC-SHA1 签名"""
        params = '&'.join(f'{k}={v}' for k, v in data.items())
        import hmac
        return hmac.new(
            key.encode('utf-8'),
            params.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()
    
    @staticmethod
    def hex_to_base64(hex_str: str) -> str:
        """Hex 转 Base64"""
        import base64
        return base64.b64encode(bytes.fromhex(hex_str)).decode('utf-8')


# ============== 认证客户端 ==============
class CloudAuthClient:
    """天翼云盘认证客户端"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': UserAgent,
            'Accept': 'application/json;charset=UTF-8'
        })
    
    def get_encrypt(self) -> Dict[str, Any]:
        """获取加密公钥"""
        resp = self.session.post(f'{AUTH_URL}/api/logbox/config/encryptConf.do')
        return resp.json()
    
    def get_login_form(self) -> Dict[str, str]:
        """获取登录表单参数"""
        params = {
            'appId': AppID,
            'clientType': ClientType,
            'returnURL': ReturnURL,
            'timeStamp': int(time.time() * 1000)
        }
        resp = self.session.get(
            f'{WEB_URL}/api/portal/unifyLoginForPC.action',
            params=params
        )
        
        if resp.text:
            captcha_token = re.search(r"'captchaToken' value='(.+?)'", resp.text)
            lt = re.search(r'lt = "(.+?)"', resp.text)
            param_id = re.search(r'paramId = "(.+?)"', resp.text)
            req_id = re.search(r'reqId = "(.+?)"', resp.text)
            
            return {
                'captchaToken': captcha_token.group(1) if captcha_token else '',
                'lt': lt.group(1) if lt else '',
                'paramId': param_id.group(1) if param_id else '',
                'reqId': req_id.group(1) if req_id else ''
            }
        return {}
    
    def get_session_for_pc(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取 PC session"""
        params.update({'appId': AppID})
        params.update(client_suffix())
        
        resp = self.session.post(
            f'{API_URL}/getSessionForPC.action',
            params=params
        )
        return resp.json()
    
    def login_by_password(self, username: str, password: str) -> Dict[str, Any]:
        """用户名密码登录"""
        print('[登录] 正在使用用户名密码登录...')
        
        # 1. 获取公钥和登录参数
        encrypt_resp = self.get_encrypt()
        app_conf = self.get_login_form()
        
        encrypt = encrypt_resp.get('data', {})
        print(f'[登录] 获取到加密参数')
        
        # 2. RSA 加密用户名和密码
        username_encrypted = CryptoUtils.rsa_encrypt(encrypt['pubKey'], username)
        password_encrypted = CryptoUtils.rsa_encrypt(encrypt['pubKey'], password)
        
        # 3. 构建登录数据
        data = {
            'appKey': AppID,
            'accountType': AccountType,
            'validateCode': '',
            'captchaToken': app_conf['captchaToken'],
            'dynamicCheck': 'FALSE',
            'clientType': '1',
            'cb_SaveName': '3',
            'isOauth2': False,
            'returnUrl': ReturnURL,
            'paramId': app_conf['paramId'],
            'userName': f"{encrypt['pre']}{username_encrypted}",
            'password': f"{encrypt['pre']}{password_encrypted}"
        }
        
        # 4. 提交登录
        headers = {
            'Referer': AUTH_URL,
            'lt': app_conf['lt'],
            'REQID': app_conf['reqId']
        }
        
        resp = self.session.post(
            f'{AUTH_URL}/api/logbox/oauth2/loginSubmit.do',
            data=data,
            headers=headers
        )
        login_res = resp.json()
        print(f'[登录] loginSubmit 返回: {login_res}')
        
        # 检查登录结果
        if login_res.get('result') != 0:
            error_msg = login_res.get('msg', 'Unknown error')
            raise RuntimeError(f'登录失败: {error_msg}')
        
        # 5. 获取 session
        to_url = login_res.get('toUrl', '')
        if not to_url:
            raise RuntimeError('登录失败: 未获取到 redirect URL')
            
        result = self.get_session_for_pc({'redirectURL': to_url})
        print(f'[登录] get_session_for_pc 返回: {result}')
        return result
    
    def login_by_access_token(self, access_token: str) -> Dict[str, Any]:
        """Token 登录"""
        print('[登录] 使用 AccessToken 登录...')
        return self.get_session_for_pc({'accessToken': access_token})
    
    def login_by_cookie(self, sso_cookie: str) -> Dict[str, Any]:
        """SSO Cookie 登录"""
        print('[登录] 使用 Cookie 登录...')
        
        params = {
            'appId': AppID,
            'clientType': ClientType,
            'returnURL': ReturnURL,
            'timeStamp': int(time.time() * 1000)
        }
        
        resp = self.session.get(
            f'{WEB_URL}/api/portal/unifyLoginForPC.action',
            params=params
        )
        
        # 使用 SSO Cookie 访问
        self.session.cookies.set('SSON', sso_cookie)
        resp = self.session.get(resp.url)
        
        return self.get_session_for_pc({'redirectURL': resp.url})
    
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新 Token"""
        data = {
            'clientId': AppID,
            'refreshToken': refresh_token,
            'grantType': 'refresh_token',
            'format': 'json'
        }
        resp = self.session.post(f'{AUTH_URL}/api/oauth2/refreshToken.do', data=data)
        return resp.json()


# ============== 云盘客户端 ==============
class Cloud189Client:
    """天翼云盘客户端"""
    
    # 项目根目录
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        cookie: Optional[str] = None,
        token_file: Optional[str] = None
    ):
        self.username = username
        self.password = password
        self.cookie = cookie
        # 与 Node.js 版本兼容的 token 路径: data/{username}.json
        if token_file:
            self.token_file = token_file
        elif username:
            self.token_file = os.path.join(self.ROOT_DIR, 'data', f'{username}.json')
        else:
            self.token_file = os.path.join(self.ROOT_DIR, 'data', 'cloud189_token.json')
        
        self.auth_client = CloudAuthClient()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': UserAgent,
            'Accept': 'application/json;charset=UTF-8',
            'Referer': f'{WEB_URL}/web/main/'
        })
        
        # Token 缓存
        self._token_info = TokenInfo()
        self._rsa_key: Optional[Dict[str, Any]] = None
        
        # 加载保存的 token
        self._load_token()
    
    def _load_token(self):
        """加载保存的 token"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 兼容驼峰命名和下划线命名
                    # expiresIn 是毫秒时间戳，转换为秒
                    expires_in = data.get('expires_in') or data.get('expiresIn', 0)
                    if expires_in > 10000000000:  # 毫秒时间戳
                        expires_at = expires_in / 1000
                    else:
                        expires_at = expires_in
                    
                    self._token_info = TokenInfo(
                        access_token=data.get('access_token') or data.get('accessToken', ''),
                        refresh_token=data.get('refresh_token') or data.get('refreshToken', ''),
                        session_key=data.get('session_key') or data.get('sessionKey', ''),
                        family_session_key=data.get('family_session_key') or data.get('familySessionKey', ''),
                        family_session_secret=data.get('family_session_secret') or data.get('familySessionSecret', ''),
                        expires_in=int(expires_in),
                        expires_at=expires_at
                    )
                    print(f'[Token] 已加载缓存的 token')
            except Exception as e:
                print(f'[Token] 加载失败: {e}')
    
    def _save_token(self):
        """保存 token（与 Node.js 版本兼容，使用驼峰命名）"""
        os.makedirs(os.path.dirname(self.token_file) or '.', exist_ok=True)
        with open(self.token_file, 'w', encoding='utf-8') as f:
            json.dump({
                'accessToken': self._token_info.access_token,
                'refreshToken': self._token_info.refresh_token,
                'sessionKey': self._token_info.session_key,
                'familySessionKey': self._token_info.family_session_key,
                'familySessionSecret': self._token_info.family_session_secret,
                'expiresIn': int(self._token_info.expires_at * 1000)  # 毫秒时间戳
            }, f, indent=2)
        print(f'[Token] 已保存 token')
    
    def _get_session(self) -> Dict[str, Any]:
        """获取 session"""
        now = time.time()
        
        # 1. 尝试使用已保存的 access token
        if self._token_info.access_token and self._token_info.expires_at > now:
            try:
                result = self.auth_client.login_by_access_token(self._token_info.access_token)
                # 检查返回结果是否有效
                if result.get('sessionKey'):
                    return result
                print(f'[登录] AccessToken 无效或已过期')
            except Exception as e:
                print(f'[登录] AccessToken 登录失败: {e}')
        
        # 2. 尝试刷新 token
        if self._token_info.refresh_token:
            try:
                refresh_result = self.auth_client.refresh_token(self._token_info.refresh_token)
                new_access_token = refresh_result.get('accessToken', '')
                if new_access_token:
                    self._token_info.access_token = new_access_token
                    self._token_info.refresh_token = refresh_result.get('refreshToken', '')
                    self._token_info.expires_at = now + 6 * 24 * 60 * 60  # 6天
                    self._save_token()
                    
                    result = self.auth_client.login_by_access_token(self._token_info.access_token)
                    if result.get('sessionKey'):
                        return result
            except Exception as e:
                print(f'[登录] Token 刷新失败: {e}')
        
        # 3. 尝试使用 Cookie
        if self.cookie:
            try:
                result = self.auth_client.login_by_cookie(self.cookie)
                if result.get('sessionKey'):
                    return result
            except Exception as e:
                print(f'[登录] Cookie 登录失败: {e}')
        
        # 4. 使用用户名密码
        if self.username and self.password:
            result = self.auth_client.login_by_password(self.username, self.password)
            return result
        
        raise RuntimeError('无法获取 session，请检查登录凭据')
    
    def get_session_key(self) -> str:
        """获取 sessionKey"""
        # 检查缓存的 session_key 是否有效（有过期时间检查）
        if self._token_info.session_key and self._token_info.expires_at > time.time():
            return self._token_info.session_key
        
        # 如果缓存过期或不存在，重新获取
        if self._token_info.session_key:
            print(f'[Token] SessionKey 可能已过期，重新获取...')
        
        result = self._get_session()
        self._token_info.session_key = result.get('sessionKey', '')
        self._token_info.access_token = result.get('accessToken', '')
        self._token_info.refresh_token = result.get('refreshToken', '')
        self._token_info.family_session_key = result.get('familySessionKey', '')
        self._token_info.family_session_secret = result.get('familySessionSecret', '')
        self._token_info.expires_at = time.time() + 6 * 24 * 60 * 60
        self._save_token()
        
        return self._token_info.session_key
    
    def get_access_token(self) -> str:
        """获取 accessToken"""
        # 如果有缓存的 token，先检查是否有效
        if self._token_info.access_token:
            return self._token_info.access_token
        
        result = self._get_session()
        print(f'[登录] _get_session 返回: {result}')
        
        # 检查返回结果
        if not result.get('sessionKey') or not result.get('accessToken'):
            # 清除无效的缓存
            self._clear_token_cache()
            raise RuntimeError('登录失败，未获取到有效的 session')
        
        self._token_info.access_token = result.get('accessToken', '')
        self._token_info.session_key = result.get('sessionKey', '')
        self._token_info.refresh_token = result.get('refreshToken', '')
        self._token_info.family_session_key = result.get('familySessionKey', '')
        self._token_info.family_session_secret = result.get('familySessionSecret', '')
        self._token_info.expires_at = time.time() + 6 * 24 * 60 * 60
        self._save_token()
        
        return self._token_info.access_token
    
    def get_family_session_key(self) -> str:
        """获取家庭云 sessionKey"""
        if not self._token_info.family_session_key:
            # 触发登录获取
            self.get_access_token()
        return self._token_info.family_session_key
    
    def _clear_token_cache(self):
        """清除 token 缓存"""
        self._token_info = TokenInfo()
        if os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
                print(f'[Token] 已清除无效的缓存文件')
            except Exception as e:
                print(f'[Token] 清除缓存文件失败: {e}')
    
    def generate_rsa_key(self, retry: bool = True) -> Dict[str, Any]:
        """获取 RSA 公钥"""
        if self._rsa_key and self._rsa_key.get('expire', 0) > time.time() * 1000:
            return self._rsa_key
        
        # 需要 sessionKey
        session_key = self.get_session_key()
        
        params = {'sessionKey': session_key}
        headers = self._sign_web_request(f'{WEB_URL}/api/security/generateRsaKey.action')
        
        resp = self.session.get(
            f'{WEB_URL}/api/security/generateRsaKey.action',
            params=params,
            headers=headers
        )
        result = resp.json()
        
        if 'errorCode' in result:
            error_code = result.get('errorCode', '')
            error_msg = result.get('errorMsg', '')
            print(f"[错误] 获取 RSA 密钥失败: {error_code} - {error_msg}")
            
            # 如果是 SessionKey 无效，清除缓存并重试一次
            if error_code in ['InvalidSessionKey', 'SessionKeyInvalid'] and retry:
                print("[重试] SessionKey 无效，清除缓存并重新登录...")
                self._clear_token_cache()
                # 强制重新获取 session
                self._token_info = TokenInfo()
                try:
                    session_key = self.get_session_key()
                    return self.generate_rsa_key(retry=False)
                except Exception as e:
                    raise RuntimeError(f"重新登录后仍然失败: {e}")
            
            raise RuntimeError(f"获取 RSA 密钥失败: {error_msg or error_code}")
        
        self._rsa_key = {
            'pubKey': result.get('pubKey', ''),
            'pkId': result.get('pkId', ''),
            'expire': result.get('expire', 0),
            'ver': result.get('ver', '')
        }
        return self._rsa_key
    
    def _build_upload_request(
        self,
        params: Dict[str, Any],
        request_uri: str,
        method: str = 'GET'
    ) -> Tuple[str, Dict[str, str]]:
        """构建上传请求的加密参数和 Headers"""
        # 先获取 RSA 密钥（可能会触发重新登录并更新 SessionKey）
        rsa_key = self.generate_rsa_key()
        # 确保 SessionKey 是最新的
        session_key = self.get_session_key()
        
        # 生成随机 UUID 和 AES 密钥
        request_id = self._random_uuid()
        uuid = self._random_string(16)
        timestamp = str(int(time.time() * 1000))
        
        # AES 加密参数
        encrypted_params = CryptoUtils.aes_ecb_encrypt(params, uuid)
        
        # RSA 加密 UUID
        encryption_text = CryptoUtils.rsa_encrypt_base64(rsa_key['pubKey'], uuid)
        
        # HMAC-SHA1 签名
        sign_data = {
            'SessionKey': session_key,
            'Operate': method,
            'RequestURI': request_uri,
            'Date': timestamp,
            'params': encrypted_params
        }
        signature = CryptoUtils.hmac_sha1(sign_data, uuid)
        
        url = f"{UPLOAD_URL}{request_uri}?params={encrypted_params}"
        headers = {
            'X-Request-Date': timestamp,
            'X-Request-ID': request_id,
            'SessionKey': session_key,
            'EncryptionText': encryption_text,
            'PkId': rsa_key['pkId'],
            'Signature': signature,
            'User-Agent': UserAgent
        }
        
        return url, headers
    
    def _random_uuid(self) -> str:
        """生成随机 UUID"""
        return secrets.token_hex(4) + '-' + secrets.token_hex(2) + '-4' + secrets.token_hex(1)[:3] + '-' + secrets.token_hex(2) + '-' + secrets.token_hex(6)
    
    def _random_string(self, length: int = 16) -> str:
        """生成随机字符串"""
        chars = '0123456789abcdef'
        return ''.join(secrets.choice(chars) for _ in range(length))
    
    def _sign_api_request(self, url: str, method: str = 'GET', data: Optional[Dict] = None) -> Dict[str, str]:
        """API 请求签名（用于 api.cloud.189.cn 域名）
        
        注意：api.cloud.189.cn 使用 SessionKey 而不是 AccessToken
        """
        # 家庭云 API 使用 sessionKey
        session_key = self.get_session_key()
        timestamp = str(int(time.time() * 1000))
        
        # 解析 URL 参数
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        query_params = {k: v[0] for k, v in query_params.items()}
        
        # 合并参数
        all_params = query_params.copy()
        if method == 'POST' and data:
            all_params.update(data)
        all_params['Timestamp'] = timestamp
        all_params['SessionKey'] = session_key
        
        # 排序并计算签名
        sorted_params = sorted(all_params.items())
        param_str = '&'.join(f'{k}={v}' for k, v in sorted_params)
        signature = hashlib.md5(param_str.encode('utf-8')).hexdigest()
        
        # 调试输出
        print(f'[Cloud189] API签名参数: {param_str}')
        print(f'[Cloud189] API签名结果: {signature}')
        print(f'[Cloud189] SessionKey: {session_key}')
        
        return {
            'Sign-Type': '1',
            'Signature': signature,
            'Timestamp': timestamp,
            'SessionKey': session_key,
            'Browser-Id': self._get_browser_id(),
            'Accept': 'application/json;charset=UTF-8',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://cloud.189.cn',
            'Referer': 'https://cloud.189.cn/'
        }
    
    def _get_browser_id(self) -> str:
        """获取或生成 browser-id"""
        if not hasattr(self, '_browser_id') or not self._browser_id:
            # 从 cookie 中提取或生成新的 browser-id
            for cookie in self.session.cookies:
                if cookie.name == 'browser-id':
                    self._browser_id = cookie.value
                    break
            else:
                # 生成新的 browser-id (32位十六进制字符串)
                self._browser_id = secrets.token_hex(16)
        return self._browser_id
    
    def _sign_web_request(self, url: str) -> Dict[str, str]:
        """Web 请求签名"""
        session_key = self.get_session_key()
        timestamp = str(int(time.time() * 1000))
        
        # AppKey 签名
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        query_params = {k: v[0] for k, v in query_params.items()}
        query_params['Timestamp'] = timestamp
        query_params['AppKey'] = '600100422'
        
        sorted_params = sorted(query_params.items())
        param_str = '&'.join(f'{k}={v}' for k, v in sorted_params)
        signature = hashlib.md5(param_str.encode('utf-8')).hexdigest()
        
        return {
            'Sign-Type': '1',
            'Signature': signature,
            'Timestamp': timestamp,
            'AppKey': '600100422',
            'SessionKey': session_key
        }
    
    # ============== 文件操作 ==============
    
    def _handle_api_error(self, result: Dict[str, Any]) -> bool:
        """
        处理 API 错误，如果是 token 失效则清除缓存
        
        Returns:
            True 如果是需要重试的 token 错误
        """
        error_code = result.get('errorCode', '')
        if error_code in ['InvalidAccessToken', 'AccessTokenInvalid', 'SessionKeyInvalid']:
            print(f'[Cloud189] Token 失效: {error_code}, 清除缓存并准备重新登录')
            self._clear_token_cache()
            return True
        return False
    
    def get_user_size_info(self) -> Dict[str, Any]:
        """获取用户网盘容量信息"""
        headers = self._sign_web_request(f'{WEB_URL}/api/portal/getUserSizeInfo.action')
        resp = self.session.get(
            f'{WEB_URL}/api/portal/getUserSizeInfo.action',
            headers=headers
        )
        return resp.json()
    
    def list_files(
        self,
        folder_id: str = '-11',
        page_num: int = 1,
        page_size: int = 60,
        family_id: Optional[str] = None,
        _retry: bool = True
    ) -> Dict[str, Any]:
        """获取文件列表
        
        Args:
            folder_id: 文件夹ID
            page_num: 页码
            page_size: 每页数量
            family_id: 家庭云ID（可选）
        """
        if family_id:
            # 家庭云使用不同的 API 端点和签名方式
            url = f'{API_URL}/open/family/file/listFiles.action'
            params = {
                'folderId': folder_id,
                'pageNum': page_num,
                'pageSize': page_size,
                'mediaType': '0',
                'familyId': family_id,
                'iconOption': '5',
                'orderBy': '3',  # 按时间排序
                'descending': 'true'
            }
            # 家庭云 API 使用 Accesstoken 签名
            headers = self._sign_api_request(url)
            resp = self.session.get(url, params=params, headers=headers)
        else:
            # 个人云
            url = f'{WEB_URL}/api/open/file/listFiles.action'
            params = {
                'folderId': folder_id,
                'pageNum': page_num,
                'pageSize': page_size,
                'mediaType': '0',
                'orderBy': 'lastOpTime',
                'descending': 'true',
                'iconOption': '5'
            }
            headers = self._sign_web_request(url)
            resp = self.session.get(url, params=params, headers=headers)
        
        result = resp.json()
        
        # 如果是 token 失效，清除缓存并重试一次
        if _retry and self._handle_api_error(result):
            return self.list_files(folder_id, page_num, page_size, family_id, _retry=False)
        
        return result
    
    def create_folder(
        self,
        folder_name: str,
        parent_folder_id: str = '-11',
        family_id: Optional[str] = None,
        _retry: bool = True
    ) -> Dict[str, Any]:
        """创建文件夹
        
        Args:
            folder_name: 文件夹名称
            parent_folder_id: 父文件夹ID
            family_id: 家庭云ID（可选，上传到家庭云时需要）
        """
        if family_id:
            # 家庭云使用不同的 API 端点和签名方式
            url = f'{API_URL}/open/family/file/createFolder.action'
            data = {
                'parentId': parent_folder_id,
                'folderName': folder_name,
                'familyId': family_id
            }
            # 家庭云 API 使用 Accesstoken 签名，签名需要包含 POST 数据
            headers = self._sign_api_request(url, method='POST', data=data)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            resp = self.session.post(url, data=data, headers=headers)
        else:
            # 个人云
            url = f'{WEB_URL}/api/open/file/createFolder.action'
            params = {
                'parentFolderId': parent_folder_id,
                'folderName': folder_name
            }
            headers = self._sign_web_request(url)
            resp = self.session.get(url, params=params, headers=headers)
        
        result = resp.json()
        print(f'[Cloud189] create_folder 返回: {result}')
        
        # 如果是 token 失效，清除缓存并重试一次
        if _retry and self._handle_api_error(result):
            return self.create_folder(folder_name, parent_folder_id, family_id, _retry=False)
        
        return result
    
    def delete_file(
        self,
        file_id: str,
        file_name: str,
        is_folder: bool = False,
        srcParentId: str = 0,
        familyId: str = 0,
        _retry: bool = True
    ) -> Dict[str, Any]:
        """
        删除文件或文件夹
        
        Args:
            file_id: 文件ID
            file_name: 文件名
            is_folder: 是否是文件夹
            _retry: 是否允许重试
        
        Returns:
            API 返回结果
        """
        import json as json_module
        
        url = f'{WEB_URL}/api/open/batch/createBatchTask.action'
            
        # 构建 taskInfos
        task_info = {
            "fileId": file_id,
            "fileName": file_name,
            "isFolder": 1 if is_folder else 0
        }

        # 如果 srcParentId 不等于 0，则添加到 task_info
        if srcParentId != 0:
            task_info["srcParentId"] = srcParentId

        
        data = {
            'type': 'DELETE',
            'taskInfos': json_module.dumps([task_info]),
            'targetFolderId': ''
        }
        
        if familyId != 0:
            data["familyId"] = familyId

        headers = self._sign_web_request(url)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        resp = self.session.post(url, data=data, headers=headers)
        result = resp.json()
        
        print(f'[Cloud189] delete_file 返回: {result}')
        
        # 如果是 token 失效，清除缓存并重试一次
        if _retry and self._handle_api_error(result):
            return self.delete_file(file_id, file_name, is_folder, srcParentId, _retry=False)
        
        return result
    
    def empty_recycle(
        self,
        familyId: str = "0",
        _retry: bool = True
    ) -> Dict[str, Any]:
        """
        清空回收站
        
        Args:
            familyId: 家庭云ID，默认为 "0"（个人云）
            _retry: 是否允许重试
        
        Returns:
            API 返回结果
        """
        url = f'{WEB_URL}/api/open/batch/createBatchTask.action'
        
        data = {
            'type': 'EMPTY_RECYCLE',
            'taskInfos': '[]',
            'targetFolderId': ''
        }
        
        if familyId and familyId != "0":
            data["familyId"] = familyId
        
        headers = self._sign_web_request(url)
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        resp = self.session.post(url, data=data, headers=headers)
        result = resp.json()
        
        print(f'[Cloud189] empty_recycle 返回: {result}')
        
        # 如果是 token 失效，清除缓存并重试一次
        if _retry and self._handle_api_error(result):
            return self.empty_recycle(familyId, _retry=False)
        
        return result
    
    def get_family_list(self, _retry: bool = True) -> List[Dict[str, Any]]:
        """
        获取家庭云列表
        
        Returns:
            家庭云信息列表，每个元素包含:
            - familyId: 家庭云ID
            - remarkName: 家庭云名称
            - createTime: 创建时间
            - userRole: 用户角色
            - count: 成员数量
        """
        url = f'{WEB_URL}/api/open/family/manage/getFamilyList.action'
        
        headers = self._sign_web_request(url)
        resp = self.session.get(url, headers=headers)
        result = resp.json()
        
        # 如果是 token 失效，清除缓存并重试一次
        if _retry and self._handle_api_error(result):
            return self.get_family_list(_retry=False)
        
        families = []
        for item in result.get('familyInfoResp', []):
            families.append({
                'familyId': item.get('familyId', 0),
                'remarkName': item.get('remarkName', ''),
                'createTime': item.get('createTime', ''),
                'userRole': item.get('userRole', 0),
                'count': item.get('count', 0),
            })
        
        return families
    
    def get_download_link(
        self,
        file_id: str,
        share_id: Optional[str] = None,
        family_id: Optional[str] = None
    ) -> Optional[str]:
        """获取文件下载链接"""
        params = {
            'fileId': file_id,
            'dt': '1'
        }
        
        if share_id:
            params['shareId'] = share_id
            params['type'] = '4'
        elif family_id:
            params['familyId'] = family_id
            params['type'] = '3'
        else:
            params['type'] = '2'
        
        url = f'{WEB_URL}/api/portal/getNewVlcVideoPlayUrl.action'
        headers = self._sign_web_request(url)
        
        resp = self.session.get(url, params=params, headers=headers)
        result = resp.json()
        
        if result.get('res_code') != 0:
            return None
        
        normal = result.get('normal', {})
        if normal.get('code') != 1:
            return None
        
        # 获取重定向后的真实链接
        redirect_resp = self.session.get(
            normal['url'],
            allow_redirects=False,
            headers={'User-Agent': UserAgent}
        )
        return redirect_resp.headers.get('Location')
    
    # ============== 上传功能 ==============
    
    def _part_size(self, file_size: int) -> int:
        """计算分片大小"""
        DEFAULT = 10 * 1024 * 1024  # 10 MB
        
        if file_size > DEFAULT * 2 * 999:  # 约 20GB 以上
            chunk_size = file_size / 1999
            ratio = chunk_size / DEFAULT
            multiplier = max(int(ratio) + (1 if ratio % 1 else 0), 5)
            return multiplier * DEFAULT
        
        if file_size > DEFAULT * 999:  # 约 10GB - 20GB
            return DEFAULT * 2  # 20 MB
        
        return DEFAULT
    
    def _calculate_md5(
        self,
        file_path: str,
        slice_size: int,
        on_progress: Optional[Callable[[int], None]] = None
    ) -> Tuple[str, List[str]]:
        """计算文件 MD5 和分片 MD5"""
        file_md5 = hashlib.md5()
        slice_md5s = []
        
        file_size = os.path.getsize(file_path)
        processed = 0
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(slice_size)
                if not chunk:
                    break
                
                # 分片 MD5 (大写)
                chunk_md5 = hashlib.md5(chunk).hexdigest().upper()
                slice_md5s.append(chunk_md5)
                
                # 文件 MD5
                file_md5.update(chunk)
                
                processed += len(chunk)
                if on_progress:
                    on_progress(int(processed / file_size * 100))
        
        return file_md5.hexdigest().upper(), slice_md5s
    
    def init_multi_upload(
        self,
        parent_folder_id: str,
        file_name: str,
        file_size: int,
        slice_size: int,
        file_md5: Optional[str] = None,
        slice_md5: Optional[str] = None,
        family_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """初始化上传"""
        params = {
            'parentFolderId': parent_folder_id,
            'fileName': quote(file_name, safe=''),
            'fileSize': file_size,
            'sliceSize': slice_size
        }
        
        if file_md5 and slice_md5:
            params['fileMd5'] = file_md5
            params['sliceMd5'] = slice_md5
        else:
            params['lazyCheck'] = '1'
        
        if family_id:
            request_uri = '/family/initMultiUpload'
            params['familyId'] = family_id
        else:
            request_uri = '/person/initMultiUpload'
        
        url, headers = self._build_upload_request(params, request_uri)
        resp = self.session.get(url, headers=headers)
        return resp.json()
    
    def check_trans_second(
        self,
        file_md5: str,
        slice_md5: str,
        upload_file_id: str,
        family_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """检测秒传"""
        params = {
            'fileMd5': file_md5,
            'sliceMd5': slice_md5,
            'uploadFileId': upload_file_id
        }
        
        if family_id:
            request_uri = '/family/checkTransSecond'
        else:
            request_uri = '/person/checkTransSecond'
        
        url, headers = self._build_upload_request(params, request_uri)
        resp = self.session.get(url, headers=headers)
        return resp.json()
    
    def get_multi_upload_urls(
        self,
        upload_file_id: str,
        part_number: int,
        md5: str,
        family_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取分片上传 URL"""
        part_info = f"{part_number}-{CryptoUtils.hex_to_base64(md5)}"
        
        params = {
            'uploadFileId': upload_file_id,
            'partInfo': part_info
        }
        
        if family_id:
            request_uri = '/family/getMultiUploadUrls'
        else:
            request_uri = '/person/getMultiUploadUrls'
        
        url, headers = self._build_upload_request(params, request_uri)
        resp = self.session.get(url, headers=headers)
        return resp.json()
    
    def commit_multi_upload(
        self,
        upload_file_id: str,
        file_md5: str,
        slice_md5: str,
        lazy_check: int = 1,
        family_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """提交上传"""
        params = {
            'uploadFileId': upload_file_id,
            'fileMd5': file_md5,
            'sliceMd5': slice_md5,
            'lazyCheck': lazy_check,
            'opertype': '3'
        }
        
        if family_id:
            request_uri = '/family/commitMultiUploadFile'
        else:
            request_uri = '/person/commitMultiUploadFile'
        
        url, headers = self._build_upload_request(params, request_uri)
        resp = self.session.get(url, headers=headers)
        return resp.json()
    
    def _upload_chunk(
        self,
        upload_file_id: str,
        part_number: int,
        data: bytes,
        md5: str,
        family_id: Optional[str] = None,
        max_retries: int = 5
    ) -> Tuple[int, bool, str]:
        """上传单个分片（带重试机制），返回 (part_number, success, error_msg)"""
        last_error = None
        
        for retry in range(max_retries):
            try:
                # 获取上传 URL（每次重试都重新获取）
                urls_result = self.get_multi_upload_urls(
                    upload_file_id, part_number, md5, family_id
                )
                
                if urls_result.get('code') != 'SUCCESS':
                    raise Exception(f"获取上传URL失败: {urls_result.get('msg')}")
                
                upload_info = urls_result['uploadUrls'][f'partNumber_{part_number}']
                request_url = upload_info['requestURL']
                request_header = upload_info['requestHeader']
                
                # 解析 headers
                headers = {}
                for pair in request_header.split('&'):
                    idx = pair.index('=')
                    headers[pair[:idx]] = pair[idx + 1:]
                
                # PUT 上传（增加超时时间和重试配置）
                resp = requests.put(
                    request_url, 
                    data=data, 
                    headers=headers, 
                    timeout=(30, 300),  # 连接超时30s，读取超时300s
                )
                resp.raise_for_status()
                
                return (part_number, True, '')
                
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                
                if retry < max_retries - 1:
                    # SSL错误使用更长等待时间
                    if 'ssl' in error_str or 'connection' in error_str:
                        wait_time = 5 + retry * 3  # 5, 8, 11, 14 秒
                    else:
                        wait_time = 2 ** retry  # 指数退避: 1, 2, 4, 8 秒
                    
                    print(f'\n[上传] 分片 {part_number} 上传失败 (尝试 {retry + 1}/{max_retries}): {e}')
                    print(f'[上传] {wait_time}秒后重试...')
                    time.sleep(wait_time)
        
        return (part_number, False, str(last_error))
    
    def _upload_chunk_with_file(
        self,
        upload_file_id: str,
        part_number: int,
        file_path: str,
        slice_size: int,
        file_size: int,
        md5: str,
        family_id: Optional[str] = None,
        max_retries: int = 5
    ) -> Tuple[int, bool, str]:
        """从文件读取并上传分片，返回 (part_number, success, error_msg)"""
        try:
            start = (part_number - 1) * slice_size
            chunk_size = min(slice_size, file_size - start)
            
            with open(file_path, 'rb') as f:
                f.seek(start)
                data = f.read(chunk_size)
            
            return self._upload_chunk(upload_file_id, part_number, data, md5, family_id, max_retries)
        except Exception as e:
            return (part_number, False, str(e))
    
    def upload_file(
        self,
        file_path: str,
        parent_folder_id: str = '-11',
        family_id: Optional[str] = None,
        max_workers: int = 5,
        show_progress: bool = True,
        on_md5_progress: Optional[Callable[[int], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        on_chunk_complete: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """上传文件（支持多线程和进度条）
        
        Args:
            file_path: 文件路径
            parent_folder_id: 目标文件夹ID，-11 为根目录
            family_id: 家庭云ID（可选）
            max_workers: 并发上传线程数，默认 5
            show_progress: 是否显示进度条，默认 True
            on_md5_progress: MD5 计算进度回调
            on_progress: 上传进度回调
            on_chunk_complete: 分片完成回调
        """
        abs_path = os.path.abspath(file_path)
        file_name = os.path.basename(abs_path)
        file_size = os.path.getsize(abs_path)
        
        print(f'[上传] 开始上传: {file_name}, 大小: {file_size / 1024 / 1024:.2f} MB')
        
        try:
            # 1. 计算分片大小
            slice_size = self._part_size(file_size)
            total_chunks = (file_size + slice_size - 1) // slice_size
            
            # 2. 计算 MD5（带进度条）
            print('[上传] 计算文件 MD5...')
            if show_progress and TQDM_AVAILABLE:
                md5_pbar = tqdm(total=100, desc='MD5计算', unit='%', ncols=80)
                last_progress = [0]
                def md5_progress_cb(p):
                    md5_pbar.update(p - last_progress[0])
                    last_progress[0] = p
                file_md5, slice_md5s = self._calculate_md5(abs_path, slice_size, md5_progress_cb)
                md5_pbar.close()
            else:
                file_md5, slice_md5s = self._calculate_md5(abs_path, slice_size, on_md5_progress)
            
            # sliceMd5: 文件 <= 10MB 时等于 fileMd5，否则为所有分片md5连接后的md5
            DEFAULT = 10 * 1024 * 1024
            if file_size > DEFAULT:
                slice_md5 = CryptoUtils.md5('\n'.join(slice_md5s)).upper()
            else:
                slice_md5 = file_md5
            
            print(f'[上传] MD5: {file_md5}, sliceMd5: {slice_md5}, 分片数: {len(slice_md5s)}')
            
            # 3. 初始化上传
            print('[上传] 初始化上传...')
            init_result = self.init_multi_upload(
                parent_folder_id=parent_folder_id,
                file_name=file_name,
                file_size=file_size,
                slice_size=slice_size,
                family_id=family_id
            )
            
            if init_result.get('code') != 'SUCCESS':
                raise RuntimeError(init_result.get('msg', '初始化上传失败'))
            
            upload_file_id = init_result['data']['uploadFileId']
            print(f'[上传] 初始化成功, uploadFileId: {upload_file_id}')
            
            # 4. 检测秒传
            print('[上传] 检测秒传...')
            check_result = self.check_trans_second(
                file_md5, slice_md5, upload_file_id, family_id
            )
            
            file_data_exists = check_result.get('data', {}).get('fileDataExists', False)
            print(f'[上传] 秒传检测结果: fileDataExists={file_data_exists}')
            
            if file_data_exists:
                # 秒传成功
                print('[上传] 秒传检测命中，直接提交...')
                commit_result = self.commit_multi_upload(
                    upload_file_id, file_md5, slice_md5, family_id=family_id
                )
                
                if commit_result.get('code') == 'SUCCESS':
                    print(f'[上传] 秒传成功: {file_name}')
                    return UploadResult(
                        success=True,
                        rapid_upload=True,
                        user_file_id=commit_result.get('file', {}).get('userFileId'),
                        file_name=file_name,
                        file_size=file_size,
                        file_md5=file_md5,
                        slice_md5=slice_md5,
                        slice_md5s=slice_md5s,
                        message='秒传成功'
                    )
                raise RuntimeError(commit_result.get('msg', '秒传提交失败'))
            
            # 5. 多线程分片上传
            print(f'[上传] 秒传未命中，开始分片上传（并发数: {max_workers}）...')
            
            # 进度条（以字节为单位，显示速度）
            if show_progress and TQDM_AVAILABLE:
                upload_pbar = tqdm(
                    total=file_size,
                    desc='上传进度',
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    ncols=100
                )
            else:
                upload_pbar = None
            
            # 线程安全的计数器
            uploaded_bytes = [0]
            start_time = time.time()
            lock = threading.Lock()
            failed_parts = []  # 记录失败的分片号
            success_parts = set()  # 记录成功的分片号
            
            def upload_single_chunk(part_number: int) -> Tuple[int, bool, str]:
                """上传单个分片的包装函数"""
                # 计算分片大小
                start_offset = (part_number - 1) * slice_size
                chunk_size = min(slice_size, file_size - start_offset)
                
                result = self._upload_chunk_with_file(
                    upload_file_id=upload_file_id,
                    part_number=part_number,
                    file_path=abs_path,
                    slice_size=slice_size,
                    file_size=file_size,
                    md5=slice_md5s[part_number - 1],
                    family_id=family_id
                )
                
                part_number, success, error_msg = result
                with lock:
                    if success:
                        success_parts.add(part_number)
                        uploaded_bytes[0] += chunk_size
                        if upload_pbar:
                            upload_pbar.update(chunk_size)
                        if on_progress:
                            on_progress(int(uploaded_bytes[0] / file_size * 100))
                        if on_chunk_complete:
                            on_chunk_complete(part_number - 1, total_chunks)
                    else:
                        failed_parts.append((part_number, error_msg))
                
                return result
            
            # 使用线程池并发上传
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(upload_single_chunk, i + 1): i + 1 
                    for i in range(total_chunks)
                }
                
                for future in as_completed(futures):
                    future.result()  # 等待完成，结果已在回调中处理
            
            # 失败分片重传（最多2轮）
            max_retry_rounds = 2
            retry_round = 0
            
            while failed_parts and retry_round < max_retry_rounds:
                retry_round += 1
                retry_parts = failed_parts[:]
                failed_parts = []
                
                print(f'\n[上传] 第{retry_round}轮重传失败分片，共 {len(retry_parts)} 个分片')
                time.sleep(3)  # 等待网络恢复
                
                for part_number, _ in retry_parts:
                    start_offset = (part_number - 1) * slice_size
                    chunk_size = min(slice_size, file_size - start_offset)
                    
                    result = self._upload_chunk_with_file(
                        upload_file_id=upload_file_id,
                        part_number=part_number,
                        file_path=abs_path,
                        slice_size=slice_size,
                        file_size=file_size,
                        md5=slice_md5s[part_number - 1],
                        family_id=family_id,
                        max_retries=5  # 重传时增加重试次数
                    )
                    
                    part_number, success, error_msg = result
                    with lock:
                        if success:
                            print(f'[上传] 分片 {part_number} 重传成功')
                            success_parts.add(part_number)
                            uploaded_bytes[0] += chunk_size
                            if upload_pbar:
                                upload_pbar.update(chunk_size)
                            if on_progress:
                                on_progress(int(uploaded_bytes[0] / file_size * 100))
                        else:
                            failed_parts.append((part_number, error_msg))
            
            if upload_pbar:
                upload_pbar.close()
                # 打印上传统计
                elapsed = time.time() - start_time
                speed = file_size / elapsed / 1024 / 1024  # MB/s
                print(f'[上传] 完成，平均速度: {speed:.2f} MB/s，耗时: {elapsed:.1f} 秒')
            
            if failed_parts:
                errors = [f"分片 {pn}: {err}" for pn, err in failed_parts]
                raise RuntimeError(f"上传失败:\n" + "\n".join(errors))
            
            # 6. 提交上传
            print('[上传] 提交上传...')
            commit_result = self.commit_multi_upload(
                upload_file_id, file_md5, slice_md5, family_id=family_id
            )
            
            if commit_result.get('code') == 'SUCCESS':
                print(f'[上传] 上传成功: {file_name}')
                return UploadResult(
                    success=True,
                    rapid_upload=False,
                    user_file_id=commit_result.get('file', {}).get('userFileId'),
                    file_name=file_name,
                    file_size=file_size,
                    file_md5=file_md5,
                    slice_md5=slice_md5,
                    slice_md5s=slice_md5s,
                    message='上传成功'
                )
            raise RuntimeError(commit_result.get('msg', '提交上传失败'))
            
        except Exception as e:
            error_msg = str(e)
            print(f'[上传] 失败: {error_msg}')
            
            # 检查是否是 SessionKey 无效错误
            if 'sessionKey' in error_msg.lower() and 'invalid' in error_msg.lower():
                print('[Cloud189] 检测到 SessionKey 无效，清除缓存')
                self._clear_token_cache()
                self._rsa_key = None  # 清除 RSA 缓存
            
            return UploadResult(
                success=False,
                message=error_msg
            )
    
    def rapid_upload(
        self,
        file_md5: str,
        file_size: int,
        slice_md5: str,
        file_name: str,
        parent_folder_id: str = '-11',
        family_id: Optional[str] = None
    ) -> UploadResult:
        """秒传文件（不实际上传，直接通过 MD5 创建文件）"""
        print(f'[秒传] {file_name}, fileMd5: {file_md5}, sliceMd5: {slice_md5}')
        
        try:
            # 1. 计算分片大小
            slice_size = self._part_size(file_size)
            
            # 2. 初始化上传
            init_result = self.init_multi_upload(
                parent_folder_id=parent_folder_id,
                file_name=file_name,
                file_size=file_size,
                slice_size=slice_size,
                family_id=family_id
            )
            
            if init_result.get('code') != 'SUCCESS':
                raise RuntimeError(init_result.get('msg', '初始化上传失败'))
            
            upload_file_id = init_result['data']['uploadFileId']
            print(f'[秒传] 初始化成功, uploadFileId: {upload_file_id}')
            
            # 3. 检测秒传
            check_result = self.check_trans_second(
                file_md5, slice_md5, upload_file_id, family_id
            )
            
            file_data_exists = check_result.get('data', {}).get('fileDataExists', False)
            print(f'[秒传] 检测结果: fileDataExists={file_data_exists}')
            
            if not file_data_exists:
                raise RuntimeError('秒传失败：文件不存在于云端')
            
            # 4. 提交秒传
            commit_result = self.commit_multi_upload(
                upload_file_id, file_md5, slice_md5, family_id=family_id
            )
            
            if commit_result.get('code') != 'SUCCESS':
                raise RuntimeError(commit_result.get('msg', '秒传提交失败'))
            
            user_file_id = commit_result.get('file', {}).get('userFileId')
            print(f'[秒传] 成功: {file_name}, userFileId: {user_file_id}')
            
            return UploadResult(
                success=True,
                rapid_upload=True,
                user_file_id=user_file_id,
                file_name=file_name,
                file_size=file_size,
                file_md5=file_md5,
                slice_md5=slice_md5,
                message='秒传成功'
            )
            
        except Exception as e:
            print(f'[秒传] 失败: {e}')
            return UploadResult(
                success=False,
                message=str(e)
            )


# ============== 测试入口 ==============
if __name__ == '__main__':
    import argparse
    from dotenv import load_dotenv
    
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='天翼云盘上传工具')
    parser.add_argument('file', help='要上传的文件路径')
    parser.add_argument('--folder', default='-11', help='目标文件夹ID，默认为根目录')
    parser.add_argument('--workers', type=int, default=5, help='并发线程数，默认 5')
    parser.add_argument('--username', help='天翼云盘用户名')
    parser.add_argument('--password', help='天翼云盘密码')
    parser.add_argument('--no-progress', action='store_true', help='禁用进度条')
    
    args = parser.parse_args()
    
    # 优先使用命令行参数，其次使用环境变量
    username = args.username or os.getenv('CLOUD189_USERNAME')
    password = args.password or os.getenv('CLOUD189_PASSWORD')
    
    if not username or not password:
        print('错误: 请提供用户名和密码')
        exit(1)
    
    # 创建客户端
    client = Cloud189Client(username=username, password=password)
    
    # 上传文件（多线程 + 进度条）
    result = client.upload_file(
        file_path=args.file,
        parent_folder_id=args.folder,
        max_workers=args.workers,
        show_progress=not args.no_progress
    )
    
    print('\n=== 上传结果 ===')
    print(f'成功: {result.success}')
    print(f'秒传: {result.rapid_upload}')
    print(f'userFileId: {result.user_file_id}')
    print(f'fileName: {result.file_name}')
    # print(f'fileSize: {result.file_size / 1024 / 1024:.2f} MB' if result.file_size else 'fileSize: N/A')
    print(f'fileSize: {result.file_size}' if result.file_size else 'fileSize: N/A')
    print(f'fileMd5: {result.file_md5}')
    print(f'sliceMd5: {result.slice_md5}')
