# app.py
from flask import Flask, request, jsonify
import requests
import os
import hashlib
from datetime import datetime, timezone, timedelta
import time
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
app.json.sort_keys = False   # ✨ YEH LINE — keys ka order preserve karega
# Agar purana Flask hai to neeche wali line use karo (dono ek saath mat rakho)
# app.config['JSON_SORT_KEYS'] = False

SESSION = requests.Session()
SESSION.verify = False
requests.packages.urllib3.disable_warnings()

# ══════════════════════════════════════════════════════════════
#   CONFIGURATION
# ══════════════════════════════════════════════════════════════
BASE_URL = "https://100067.connect.garena.com"
APP_ID = "100067"

PLATFORM_MAP = {
    3: "Facebook",
    4: "Guest",
    5: "VK",
    8: "Google",
    10: "AppleId",
    11: "X (Twitter)"
}


# ══════════════════════════════════════════════════════════════
#   AUTO-DETECT BASE URL
# ══════════════════════════════════════════════════════════════
def get_base_url():
    vercel_url = os.environ.get("VERCEL_URL")
    if vercel_url:
        return f"https://{vercel_url}"
    api_base = os.environ.get("API_BASE_URL")
    if api_base:
        return api_base.rstrip("/")
    try:
        return request.host_url.rstrip("/")
    except Exception:
        pass
    port = os.environ.get("PORT", "8001")
    return f"http://127.0.0.1:{port}"


def get_credits():
    return {
        "🎯 Credit": "KHAN",
        "📢 Join For More": "Telegram: @KHAN",
        "🌐 Base URL": get_base_url()
    }


# ══════════════════════════════════════════════════════════════
#   LOGGING
# ══════════════════════════════════════════════════════════════
def log_info(message):
    print(f"[INFO] {message}")


def log_error(message):
    print(f"[ERROR] {message}")


# ══════════════════════════════════════════════════════════════
#   HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════
def sha256_upper(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()


def convert_seconds(seconds: int) -> dict:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    if minutes > 0: parts.append(f"{minutes}m")
    if secs > 0 or not parts: parts.append(f"{secs}s")
    return {
        "total_seconds": seconds,
        "human_readable": " ".join(parts)
    }


def get_token_inspect_data(access_token: str):
    try:
        resp = SESSION.get(
            f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}",
            timeout=10
        )
        data = resp.json()
        if 'open_id' in data and 'platform' in data:
            platform_type = data.get('platform', 4)
            platform_name = PLATFORM_MAP.get(platform_type, "Unknown")
            return {
                "open_id": data.get('open_id'),
                "platform_type": platform_type,
                "platform_name": platform_name,
                "success": True
            }
    except Exception as e:
        log_error(f"Error inspecting token: {e}")
    return {"success": False, "error": "INVALID_TOKEN"}


def eat_to_access_token(eat_token: str):
    try:
        callback_url = f"https://api-otrss.garena.com/support/callback/?access_token={eat_token}"
        resp = SESSION.get(callback_url, allow_redirects=True, timeout=20)
        if 'help.garena.com' in resp.url:
            parsed = urlparse(resp.url)
            params = parse_qs(parsed.query)
            if 'access_token' in params:
                return {
                    "success": True,
                    "access_token": params['access_token'][0],
                    "region": params.get('region', [''])[0],
                    "game_uid": params.get('account_id', [''])[0],
                    "nickname": params.get('nickname', [''])[0]
                }
        return {"success": False, "error": "INVALID_EAT_TOKEN"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_recovery_status(current_email: str, pending_email: str, countdown: int) -> dict:
    has_current = bool(current_email and current_email.strip())
    has_pending = bool(pending_email and pending_email.strip())
    has_countdown = countdown > 0

    if has_current and not has_pending:
        if has_countdown:
            return {
                "status": "REMOVAL_SCHEDULED",
                "description": f"Recovery email '{current_email}' is scheduled to be removed in {countdown} seconds",
                "change_type": "removal"
            }
        else:
            return {
                "status": "SET_NO_CHANGE",
                "description": f"Recovery email is set to '{current_email}'. No changes pending.",
                "change_type": "none"
            }
    elif not has_current and has_pending:
        if has_countdown:
            return {
                "status": "ADDITION_SCHEDULED",
                "description": f"Recovery email '{pending_email}' is scheduled to be added in {countdown} seconds",
                "change_type": "addition"
            }
        else:
            return {
                "status": "PENDING_NO_COUNTDOWN",
                "description": f"Recovery email '{pending_email}' is pending but no countdown found",
                "change_type": "unknown"
            }
    elif has_current and has_pending:
        if has_countdown and current_email != pending_email:
            return {
                "status": "CHANGE_SCHEDULED",
                "description": f"Recovery email will be changed from '{current_email}' to '{pending_email}' in {countdown} seconds",
                "change_type": "change"
            }
        else:
            return {
                "status": "BOTH_SET_NO_CHANGE",
                "description": f"Both current and pending emails exist without countdown",
                "change_type": "unknown"
            }
    else:
        return {
            "status": "NOT_SET",
            "description": "No recovery email is set for this account",
            "change_type": "none"
        }


def get_recovery_email_status(access_token: str):
    start = time.time()
    try:
        url = f"{BASE_URL}/game/account_security/bind:get_bind_info?app_id={APP_ID}&access_token={access_token}"
        resp = SESSION.get(url, timeout=10)
        data = resp.json()

        if data.get('result') != 0:
            return {
                "success": False,
                "error": "API_ERROR",
                "message": "Failed to get recovery email info",
                "details": data,
                "api_time": round(time.time() - start, 3)
            }

        current = data.get('email', '')
        pending = data.get('email_to_be', '')
        countdown = data.get('request_exec_countdown', 0)
        status_info = analyze_recovery_status(current, pending, countdown)
        token_info = get_token_inspect_data(access_token)

        response = {
            "success": True,
            "recovery_email": {
                "current": current if current else "Not set",
                "pending_change": pending if pending else "No pending change",
                "countdown_seconds": countdown,
                "countdown_human": convert_seconds(countdown)["human_readable"] if countdown > 0 else None,
                "status": status_info['status'],
                "description": status_info['description'],
                "change_type": status_info['change_type']
            },
            "account_info": {
                "platform": token_info.get('platform_name') if token_info.get('success') else "Unknown",
                "platform_type": token_info.get('platform_type') if token_info.get('success') else None,
                "open_id": token_info.get('open_id') if token_info.get('success') else None
            },
            "api_time": round(time.time() - start, 3)
        }

        now = datetime.now(timezone.utc)
        response['timestamp'] = {
            "utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ist": (now + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST"),
            "unix": int(time.time())
        }
        return response
    except Exception as e:
        log_error(f"Error in get_recovery_email_status: {e}")
        return {
            "success": False,
            "error": "CHECK_ERROR",
            "message": str(e),
            "api_time": round(time.time() - start, 3)
        }


# ══════════════════════════════════════════════════════════════
#   GARENA BINDING API CLASS
# ══════════════════════════════════════════════════════════════
class GarenaBind:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = BASE_URL
        self.app_id = APP_ID
        self.session = SESSION

    def _request(self, method, endpoint, data=None, params=None, headers=None):
        url = f"{self.base_url}{endpoint}"
        default_headers = {
            'User-Agent': 'GarenaMSDK/4.0.19P9(Redmi Note 5;Android 9;en;US;)',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip'
        }
        if headers:
            default_headers.update(headers)
        try:
            if method.upper() == 'GET':
                r = self.session.get(url, params=params, headers=default_headers, timeout=10)
            else:
                r = self.session.post(url, data=data, headers=default_headers, timeout=10)
            return r.status_code, r.json() if r.text else {}
        except Exception as e:
            return 500, {"error": str(e)}

    def get_bind_info(self):
        endpoint = "/game/account_security/bind:get_bind_info"
        params = {'app_id': self.app_id, 'access_token': self.access_token}
        code, data = self._request('GET', endpoint, params=params)
        if code == 200:
            return data
        return {"error": "HTTP " + str(code)}

    def cancel_request(self):
        endpoint = "/game/account_security/bind:cancel_request"
        data = {'app_id': self.app_id, 'access_token': self.access_token}
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def send_otp(self, email):
        endpoint = "/game/account_security/bind:send_otp"
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'email': email,
            'locale': 'en_MA'
        }
        headers = {
            'Accept': 'application/json',
            'Cookie': 'datadome=q2ZtAABCjPFEIWeaxYM2YvfxEUPXT_GLUp4gpUOEUPlI9jGXkQLS5uoG_HBUBnJvC0s0CBfHF6h4FUg7mBumLRO1jpLh4um4CbF4ykEKTLv5f27DgR_nkEJcZm_Sj1E~'
        }
        code, resp = self._request('POST', endpoint, data=data, headers=headers)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def verify_otp(self, otp, email):
        endpoint = "/game/account_security/bind:verify_otp"
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'otp': otp,
            'email': email
        }
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def verify_identity(self, security_code):
        endpoint = "/game/account_security/bind:verify_identity"
        hashed = sha256_upper(security_code)
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'secondary_password': hashed
        }
        headers = {
            'User-Agent': 'GarenaMSDK/4.0.19P10(ASUS_Z01QD;Android 9;en;US;)',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'com.garena.game.kgid'
        }
        code, resp = self._request('POST', endpoint, data=data, headers=headers)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def verify_identity_with_otp(self, email, otp):
        endpoint = "/game/account_security/bind:verify_identity_with_otp"
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'email': email,
            'otp': otp
        }
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def bind_email(self, verifier_token, email, security_code):
        endpoint = "/game/account_security/bind:create_bind_request"
        hashed = sha256_upper(security_code)
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'verifier_token': verifier_token,
            'secondary_password': hashed,
            'email': email
        }
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def create_unbind_request(self, identity_token):
        endpoint = "/game/account_security/bind:create_unbind_request"
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'identity_token': identity_token
        }
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}

    def create_rebind_request(self, identity_token, verifier_token, new_email):
        endpoint = "/game/account_security/bind:create_rebind_request"
        data = {
            'app_id': self.app_id,
            'access_token': self.access_token,
            'identity_token': identity_token,
            'verifier_token': verifier_token,
            'email': new_email
        }
        code, resp = self._request('POST', endpoint, data=data)
        return resp if code == 200 else {"error": "HTTP " + str(code)}


# ══════════════════════════════════════════════════════════════
#   RESPONSE BUILDER
# ══════════════════════════════════════════════════════════════
def build_response(success, title, code, total_time, api_time, sections=None, error=None, examples=None):
    resp = {
        **get_credits(),
        "═══════════════════════════════════": "═══════════════════════════════════",
        "✅ STATUS": title,
        "🔢 Response Code": code,
    }

    if error:
        resp["❌ Error"] = error

    resp["─────────── ⏱️ TIMING ───────────"] = "───────────────────────────────────"
    resp["⏳ Total Time"] = f"{total_time} sec"
    resp["🌐 API Time"] = f"{api_time} sec"

    if sections:
        for section_name, section_data in sections.items():
            resp[f"─────────── {section_name} ───────────"] = "───────────────────────────────────"
            resp.update(section_data)

    if examples:
        resp["═══════════ 💡 EXAMPLES ═══════════"] = "═══════════════════════════════════"
        for k, v in examples.items():
            resp[k] = v

    return resp


# ══════════════════════════════════════════════════════════════
#   HOME
# ══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    base = get_base_url()
    return jsonify({
        "🎯 Credit": "KHAN",
        "📢 Join For More": "Telegram: @KHAN",
        "🌐 Base URL": base,

        "═══════════════════════════════════": "═══════════════════════════════════",
        "⚙️ SERVICE INFO": "Garena Account Management API",
        "🔢 VERSION": "5.0 (No JWT)",
        "✅ STATUS": "🟢 ONLINE",

        "═══════════════ 📡 ENDPOINTS ═══════════════": "═══════════════════════════════════",

        "🔍 1. CHECK RECOVERY": {
            "endpoint": "/check-recovery",
            "alias": "/checkbind",
            "method": "GET",
            "params": "eat OR access",
            "example": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN"
        },

        "📮 2. SEND OTP": {
            "endpoint": "/sendotp",
            "method": "GET",
            "params": "eat OR access, email",
            "example": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com"
        },

        "🔗 3. BIND EMAIL": {
            "endpoint": "/bindemail",
            "method": "GET",
            "params": "eat OR access, email, otp, security_code",
            "example": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email=user@example.com&otp=123456&security_code=abcd1234"
        },

        "🔄 4. CHANGE EMAIL": {
            "endpoint": "/changeemail",
            "method": "GET",
            "params": "new_email, new_otp, (security_code OR current_email+otp)",
            "example_1": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
            "example_2": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&current_email=old@example.com&otp=654321"
        },

        "🔓 5. UNBIND EMAIL": {
            "endpoint": "/unbindemail",
            "method": "GET",
            "params": "eat OR access, security_code",
            "example": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
        },

        "❌ 6. CANCEL REQUEST": {
            "endpoint": "/cancelrequest",
            "method": "GET",
            "params": "eat OR access",
            "example": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
        },

        "📱 7. PLATFORMS": {
            "endpoint": "/platforms",
            "method": "GET",
            "params": "none",
            "example": f"{base}/platforms"
        },

        "═══════════════ 💡 QUICK FLOW ═══════════════": "═══════════════════════════════════",
        "📝 Step 1": "Send OTP → /sendotp?access=TOKEN&email=xxx",
        "📝 Step 2": "Bind Email → /bindemail?access=TOKEN&email=xxx&otp=123456&security_code=xxx",
        "📝 Step 3": "Check Status → /check-recovery?access=TOKEN",
        "📝 Cancel": "Cancel → /cancelrequest?access=TOKEN",

        "═══════════════ 🔑 TOKEN TYPES ═══════════════": "═══════════════════════════════════",
        "🅰️ access": "Garena Access Token (direct)",
        "🅱️ eat": "EAT Token (auto-converted to access)",

        "═══════════════ ⚠️ NOTE ═══════════════": "═══════════════════════════════════",
        "💡 Note": "Provide EITHER 'eat' OR 'access', not both",
        "⏱️ Timeout": "10 seconds per request",
        "⚡ Fast": "Session reuse enabled"
    })


def get_access_token_from_args(args):
    eat = args.get('eat')
    access = args.get('access')
    if not eat and not access:
        return None, "Either 'eat' or 'access' parameter is required"
    if eat and access:
        return None, "Provide either 'eat' or 'access', not both"
    if eat:
        conv = eat_to_access_token(eat)
        if not conv.get('success'):
            return None, conv.get('error', 'EAT conversion failed')
        return conv['access_token'], None
    return access, None


# ─────────────────────────────────────────────
#   /check-recovery & /checkbind
# ─────────────────────────────────────────────
@app.route('/check-recovery', methods=['GET'])
@app.route('/checkbind', methods=['GET'])
def check_recovery():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ Correct": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
                "✅ With EAT": f"{base}/check-recovery?eat=YOUR_EAT_TOKEN"
            }
        )), 400

    result = get_recovery_email_status(token)
    api_time = result.get('api_time', 0.0)
    total_time = round(time.time() - request_start, 3)

    if not result.get('success'):
        return jsonify(build_response(
            False, "❌ Failed", 400, total_time, api_time,
            error=result.get('message', 'Failed to check recovery'),
            examples={
                "🔄 Try again": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN"
            }
        )), 400

    sections = {
        "📧 RECOVERY EMAIL": {
            "📩 Current": result['recovery_email']['current'],
            "⏳ Pending": result['recovery_email']['pending_change'],
            "⏱️ Countdown": result['recovery_email']['countdown_human'] or "N/A",
            "🔢 Countdown (sec)": result['recovery_email']['countdown_seconds'],
            "📊 Status": result['recovery_email']['status'],
            "📝 Description": result['recovery_email']['description'],
            "🔀 Change Type": result['recovery_email']['change_type']
        },
        "👤 ACCOUNT INFO": {
            "📱 Platform": result['account_info']['platform'],
            "🔢 Platform Type": result['account_info']['platform_type'],
            "🆔 Open ID": result['account_info']['open_id']
        },
        "🕐 TIMESTAMP": {
            "🌍 UTC": result['timestamp']['utc'],
            "🇮🇳 IST": result['timestamp']['ist'],
            "🔢 Unix": result['timestamp']['unix']
        }
    }

    if request.args.get('eat'):
        conv = eat_to_access_token(request.args.get('eat'))
        if conv.get('success'):
            sections["🔑 EAT CONVERSION"] = {
                "🌍 Region": conv.get('region'),
                "🆔 Game UID": conv.get('game_uid'),
                "🏷️ Nickname": conv.get('nickname')
            }

    return jsonify(build_response(
        True, "✅ Success", 200, total_time, api_time, sections,
        examples={
            "📮 Send OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com",
            "🔄 Change Email": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
            "❌ Cancel Request": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
        }
    ))


# ─────────────────────────────────────────────
#   /platforms
# ─────────────────────────────────────────────
@app.route('/platforms', methods=['GET'])
def platforms():
    request_start = time.time()
    base = get_base_url()
    return jsonify(build_response(
        True, "✅ Success", 200,
        round(time.time() - request_start, 3), 0.0,
        {
            "📱 PLATFORMS": {v: k for k, v in PLATFORM_MAP.items()},
            "ℹ️ INFO": {"🔢 Total Platforms": len(PLATFORM_MAP)}
        },
        examples={
            "🔍 Check Recovery": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
            "📮 Send OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com"
        }
    ))


# ─────────────────────────────────────────────
#   /sendotp
# ─────────────────────────────────────────────
@app.route('/sendotp', methods=['GET'])
def send_otp():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ Correct": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com"
            }
        )), 400

    email = request.args.get('email')
    if not email:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="email parameter required",
            examples={
                "✅ Correct": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com"
            }
        )), 400

    api_start = time.time()
    api = GarenaBind(token)
    resp = api.send_otp(email)
    api_time = round(time.time() - api_start, 3)
    total_time = round(time.time() - request_start, 3)

    if resp.get('result') == 0:
        return jsonify(build_response(
            True, "✅ OTP Sent", 200, total_time, api_time,
            {
                "📧 EMAIL INFO": {"📩 Email": email},
                "📡 SERVER": {"📨 Response": resp}
            },
            examples={
                "🔗 Next: Bind Email": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email={email}&otp=123456&security_code=abcd1234",
                "🔄 Change Email": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email={email}&new_otp=123456&security_code=abcd1234"
            }
        ))

    return jsonify(build_response(
        False, "❌ Failed", 400, total_time, api_time,
        {"📧 EMAIL INFO": {"📩 Email": email}},
        error=resp.get('message', 'Failed to send OTP'),
        examples={
            "🔄 Try again": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email={email}"
        }
    )), 400


# ─────────────────────────────────────────────
#   /bindemail
# ─────────────────────────────────────────────
@app.route('/bindemail', methods=['GET'])
def bind_email():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ Correct": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email=user@example.com&otp=123456&security_code=abcd1234"
            }
        )), 400

    email = request.args.get('email')
    otp = request.args.get('otp')
    sec = request.args.get('security_code')

    if not all([email, otp, sec]):
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="email, otp, security_code required",
            examples={
                "✅ Correct": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email=user@example.com&otp=123456&security_code=abcd1234"
            }
        )), 400

    api_start = time.time()
    api = GarenaBind(token)

    verify = api.verify_otp(otp, email)
    if verify.get('result') != 0:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ OTP Verification Failed", 400,
            round(time.time() - request_start, 3), api_time,
            {"📧 EMAIL INFO": {"📩 Email": email}},
            error="OTP verification failed",
            examples={
                "📮 Resend OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email={email}",
                "🔄 Try again": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email={email}&otp=NEW_OTP&security_code=abcd1234"
            }
        )), 400

    verifier = verify.get('verifier_token')
    bind_resp = api.bind_email(verifier, email, sec)
    api_time = round(time.time() - api_start, 3)
    total_time = round(time.time() - request_start, 3)

    if bind_resp.get('result') == 0:
        return jsonify(build_response(
            True, "✅ Bind Request Created", 200, total_time, api_time,
            {
                "📧 EMAIL INFO": {"📩 Email": email},
                "📡 SERVER": {"📨 Response": bind_resp}
            },
            examples={
                "🔍 Check Status": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
                "❌ Cancel Request": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
            }
        ))

    return jsonify(build_response(
        False, "❌ Bind Failed", 400, total_time, api_time,
        {"📧 EMAIL INFO": {"📩 Email": email}},
        error="Bind failed",
        examples={
            "📮 Resend OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email={email}",
            "🔄 Try again": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email={email}&otp=NEW_OTP&security_code=abcd1234"
        }
    )), 400


# ─────────────────────────────────────────────
#   /cancelrequest
# ─────────────────────────────────────────────
@app.route('/cancelrequest', methods=['GET'])
def cancel_request():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ Correct": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
            }
        )), 400

    api_start = time.time()
    api = GarenaBind(token)
    resp = api.cancel_request()
    api_time = round(time.time() - api_start, 3)
    total_time = round(time.time() - request_start, 3)

    if resp.get('result') == 0:
        return jsonify(build_response(
            True, "✅ Request Cancelled", 200, total_time, api_time,
            {"📡 SERVER": {"📨 Response": resp}},
            examples={
                "🔍 Check Status": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
                "📮 Send OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com"
            }
        ))

    return jsonify(build_response(
        False, "❌ Cancel Failed", 400, total_time, api_time,
        error="Cancel failed",
        examples={
            "🔄 Try again": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
        }
    )), 400


# ─────────────────────────────────────────────
#   /unbindemail
# ─────────────────────────────────────────────
@app.route('/unbindemail', methods=['GET'])
def unbind_email():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ Correct": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
            }
        )), 400

    sec = request.args.get('security_code')
    if not sec:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="security_code required",
            examples={
                "✅ Correct": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
            }
        )), 400

    api_start = time.time()
    api = GarenaBind(token)

    verify = api.verify_identity(sec)
    if verify.get('result') != 0:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ Identity Verification Failed", 400,
            round(time.time() - request_start, 3), api_time,
            error="Identity verification failed",
            examples={
                "🔄 Try again": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
            }
        )), 400

    identity_token = verify.get('identity_token')
    if not identity_token:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ No Identity Token", 500,
            round(time.time() - request_start, 3), api_time,
            error="No identity token in response",
            examples={
                "🔄 Try again": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
            }
        )), 500

    unbind = api.create_unbind_request(identity_token)
    api_time = round(time.time() - api_start, 3)
    total_time = round(time.time() - request_start, 3)

    if unbind.get('result') == 0:
        return jsonify(build_response(
            True, "✅ Unbind Request Created", 200, total_time, api_time,
            {"📡 SERVER": {"📨 Response": unbind}},
            examples={
                "🔍 Check Status": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
                "❌ Cancel Request": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
            }
        ))

    return jsonify(build_response(
        False, "❌ Unbind Failed", 400, total_time, api_time,
        error="Unbind failed",
        examples={
            "🔄 Try again": f"{base}/unbindemail?access=YOUR_ACCESS_TOKEN&security_code=abcd1234"
        }
    )), 400


# ─────────────────────────────────────────────
#   /changeemail
# ─────────────────────────────────────────────
@app.route('/changeemail', methods=['GET'])
def change_email():
    request_start = time.time()
    base = get_base_url()
    token, err = get_access_token_from_args(request.args)

    if err:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error=err,
            examples={
                "✅ With Security Code": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
                "✅ With OTP": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&current_email=old@example.com&otp=654321"
            }
        )), 400

    new_email = request.args.get('new_email')
    new_otp = request.args.get('new_otp')

    if not new_email or not new_otp:
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="new_email and new_otp required",
            examples={
                "✅ With Security Code": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
                "✅ With OTP": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&current_email=old@example.com&otp=654321"
            }
        )), 400

    sec = request.args.get('security_code')
    cur_email = request.args.get('current_email')
    cur_otp = request.args.get('otp')

    if not sec and not (cur_email and cur_otp):
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="Either security_code or (current_email+otp) required",
            examples={
                "✅ With Security Code": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
                "✅ With OTP": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&current_email=old@example.com&otp=654321"
            }
        )), 400

    if sec and (cur_email or cur_otp):
        return jsonify(build_response(
            False, "❌ Error", 400,
            round(time.time() - request_start, 3), 0.0,
            error="Provide only one verification method",
            examples={
                "✅ With Security Code": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
                "✅ With OTP": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&current_email=old@example.com&otp=654321"
            }
        )), 400

    api_start = time.time()
    api = GarenaBind(token)

    if sec:
        verify = api.verify_identity(sec)
    else:
        verify = api.verify_identity_with_otp(cur_email, cur_otp)

    if verify.get('result') != 0:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ Identity Verification Failed", 400,
            round(time.time() - request_start, 3), api_time,
            error="Identity verification failed",
            examples={
                "🔄 Try again": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234"
            }
        )), 400

    identity_token = verify.get('identity_token')
    if not identity_token:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ No Identity Token", 500,
            round(time.time() - request_start, 3), api_time,
            error="No identity token",
            examples={
                "🔄 Try again": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234"
            }
        )), 500

    otp_verify = api.verify_otp(new_otp, new_email)
    if otp_verify.get('result') != 0:
        api_time = round(time.time() - api_start, 3)
        return jsonify(build_response(
            False, "❌ New Email OTP Failed", 400,
            round(time.time() - request_start, 3), api_time,
            {"📧 NEW EMAIL": {"📩 Email": new_email}},
            error="New email OTP verification failed",
            examples={
                "📮 Resend OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email={new_email}"
            }
        )), 400

    verifier = otp_verify.get('verifier_token')
    rebind = api.create_rebind_request(identity_token, verifier, new_email)
    api_time = round(time.time() - api_start, 3)
    total_time = round(time.time() - request_start, 3)

    if rebind.get('result') == 0:
        return jsonify(build_response(
            True, "✅ Change Request Created", 200, total_time, api_time,
            {
                "📧 EMAIL INFO": {
                    "📤 New Email": new_email,
                    "📥 Old Email": cur_email or "N/A (verified via security code)"
                },
                "📡 SERVER": {"📨 Response": rebind}
            },
            examples={
                "🔍 Check Status": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
                "❌ Cancel Request": f"{base}/cancelrequest?access=YOUR_ACCESS_TOKEN"
            }
        ))

    return jsonify(build_response(
        False, "❌ Change Failed", 400, total_time, api_time,
        error="Change failed",
        examples={
            "🔄 Try again": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email={new_email}&new_otp=123456&security_code=abcd1234"
        }
    )), 400


# ══════════════════════════════════════════════════════════════
#   ERROR HANDLERS
# ══════════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    base = get_base_url()
    return jsonify({
        **get_credits(),
        "═══════════════════════════════════": "═══════════════════════════════════",
        "✅ STATUS": "❌ Endpoint Not Found",
        "🔢 Response Code": 404,

        "═══════════ 📡 AVAILABLE ═══════════": "═══════════════════════════════════",
        "1": "/check-recovery",
        "2": "/checkbind",
        "3": "/sendotp",
        "4": "/bindemail",
        "5": "/cancelrequest",
        "6": "/unbindemail",
        "7": "/changeemail",
        "8": "/platforms",

        "═══════════ 💡 EXAMPLES ═══════════": "═══════════════════════════════════",
        "🔍 Check Recovery": f"{base}/check-recovery?access=YOUR_ACCESS_TOKEN",
        "📮 Send OTP": f"{base}/sendotp?access=YOUR_ACCESS_TOKEN&email=user@example.com",
        "🔗 Bind Email": f"{base}/bindemail?access=YOUR_ACCESS_TOKEN&email=user@example.com&otp=123456&security_code=abcd1234",
        "🔄 Change Email": f"{base}/changeemail?access=YOUR_ACCESS_TOKEN&new_email=new@example.com&new_otp=123456&security_code=abcd1234",
        "📱 Platforms": f"{base}/platforms"
    }), 404


@app.errorhandler(500)
def server_error(e):
    base = get_base_url()
    return jsonify({
        **get_credits(),
        "✅ STATUS": "❌ Internal Server Error",
        "🔢 Response Code": 500,
        "💡 Try": f"{base}/"
    }), 500


# ══════════════════════════════════════════════════════════════
#   RUN
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8001))
    log_info(f'Starting Garena Account Management API on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)