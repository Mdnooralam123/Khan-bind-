from flask import Flask, request, jsonify
import requests
import os
import hashlib
from datetime import datetime, timezone, timedelta
import time
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)
SESSION = requests.Session()
SESSION.verify = False  # Disable SSL verification (optional)
requests.packages.urllib3.disable_warnings()

# ====================== CONFIGURATION ======================
BASE_URL = "https://100067.connect.garena.com"
APP_ID = "100067"

# Platform Mapping (used in token inspect)
PLATFORM_MAP = {
    3: "Facebook",
    4: "Guest",
    5: "VK",
    8: "Google",
    10: "AppleId",
    11: "X (Twitter)"
}

# ====================== LOGGING ======================
def log_info(message):
    print(f"[INFO] {message}")

def log_error(message):
    print(f"[ERROR] {message}")

# ====================== HELPER FUNCTIONS ======================
def sha256_upper(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest().upper()

def convert_seconds(seconds: int) -> dict:
    """Convert seconds to human readable format."""
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
    """Inspect access token and return platform info."""
    try:
        resp = SESSION.get(
            f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}",
            timeout=15
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
    """Convert EAT token to access token."""
    try:
        callback_url = f"https://api-otrss.garena.com/support/callback/?access_token={eat_token}"
        resp = SESSION.get(callback_url, allow_redirects=True, timeout=30)
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
    """Analyze recovery email status."""
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
    """Check recovery email status."""
    try:
        url = f"{BASE_URL}/game/account_security/bind:get_bind_info?app_id={APP_ID}&access_token={access_token}"
        resp = SESSION.get(url, timeout=15)
        data = resp.json()
        if data.get('result') != 0:
            return {"success": False, "error": "API_ERROR", "message": "Failed to get recovery email info", "details": data}
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
            }
        }
        # Add timestamp
        now = datetime.now(timezone.utc)
        response['timestamp'] = {
            "utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "ist": (now + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S IST"),
            "unix": int(time.time())
        }
        return response
    except Exception as e:
        log_error(f"Error in get_recovery_email_status: {e}")
        return {"success": False, "error": "CHECK_ERROR", "message": str(e)}

# ====================== GARENA BINDING API CLASS ======================
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
                r = self.session.get(url, params=params, headers=default_headers, timeout=15)
            else:
                r = self.session.post(url, data=data, headers=default_headers, timeout=15)
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

# ====================== FLASK ENDPOINTS ======================
@app.route('/')
def index():
    return jsonify({
        "success": True,
        "message": "Garena Account Management API",
        "version": "5.0 (No JWT)",
        "endpoints": {
            "/check-recovery": "Check recovery email status (eat or access)",
            "/checkbind": "Alias for /check-recovery",
            "/sendotp": "Send OTP to email (eat or access, email)",
            "/bindemail": "Bind email using OTP and security_code",
            "/cancelrequest": "Cancel any pending bind/unbind/change request",
            "/unbindemail": "Unbind email using security_code",
            "/changeemail": "Change recovery email",
            "/platforms": "Get supported platform types"
        },
        "credits": {
            "developer": "@DANGER_FF_LIKE",
            "main_channel": "@freefirelikesdanger",
            "apis_channel": "@dangerfreeapis"
        }
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

@app.route('/check-recovery', methods=['GET'])
@app.route('/checkbind', methods=['GET'])
def check_recovery():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    result = get_recovery_email_status(token)
    # Add conversion info if EAT was used
    if request.args.get('eat') and result.get('success'):
        conv = eat_to_access_token(request.args.get('eat'))
        if conv.get('success'):
            result['eat_conversion'] = {
                "region": conv.get('region'),
                "game_uid": conv.get('game_uid'),
                "nickname": conv.get('nickname')
            }
    if result.get('success'):
        result['credits'] = {
            "developer": "@DANGER_FF_LIKE",
            "main_channel": "@freefirelikesdanger",
            "apis_channel": "@dangerfreeapis"
        }
    return jsonify(result)

@app.route('/platforms', methods=['GET'])
def platforms():
    return jsonify({
        "success": True,
        "platforms": PLATFORM_MAP,
        "total_platforms": len(PLATFORM_MAP),
        "credits": {
            "developer": "@DANGER_FF_LIKE",
            "main_channel": "@freefirelikesdanger",
            "apis_channel": "@dangerfreeapis"
        }
    })

@app.route('/sendotp', methods=['GET'])
def send_otp():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    email = request.args.get('email')
    if not email:
        return jsonify({"success": False, "error": "email parameter required"}), 400
    api = GarenaBind(token)
    resp = api.send_otp(email)
    if resp.get('result') == 0:
        return jsonify({"success": True, "message": "OTP sent", "data": resp})
    return jsonify({"success": False, "error": resp.get('message', 'Failed'), "details": resp}), 400

@app.route('/bindemail', methods=['GET'])
def bind_email():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    email = request.args.get('email')
    otp = request.args.get('otp')
    sec = request.args.get('security_code')
    if not all([email, otp, sec]):
        return jsonify({"success": False, "error": "email, otp, security_code required"}), 400
    api = GarenaBind(token)
    # Verify OTP first
    verify = api.verify_otp(otp, email)
    if verify.get('result') != 0:
        return jsonify({"success": False, "error": "OTP verification failed", "details": verify}), 400
    verifier = verify.get('verifier_token')
    bind_resp = api.bind_email(verifier, email, sec)
    if bind_resp.get('result') == 0:
        return jsonify({"success": True, "message": "Bind request created", "data": bind_resp})
    return jsonify({"success": False, "error": "Bind failed", "details": bind_resp}), 400

@app.route('/cancelrequest', methods=['GET'])
def cancel_request():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    api = GarenaBind(token)
    resp = api.cancel_request()
    if resp.get('result') == 0:
        return jsonify({"success": True, "message": "Request cancelled", "data": resp})
    return jsonify({"success": False, "error": "Cancel failed", "details": resp}), 400

@app.route('/unbindemail', methods=['GET'])
def unbind_email():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    sec = request.args.get('security_code')
    if not sec:
        return jsonify({"success": False, "error": "security_code required"}), 400
    api = GarenaBind(token)
    # Verify identity
    verify = api.verify_identity(sec)
    if verify.get('result') != 0:
        return jsonify({"success": False, "error": "Identity verification failed", "details": verify}), 400
    identity_token = verify.get('identity_token')
    if not identity_token:
        return jsonify({"success": False, "error": "No identity token in response", "details": verify}), 500
    unbind = api.create_unbind_request(identity_token)
    if unbind.get('result') == 0:
        return jsonify({"success": True, "message": "Unbind request created", "data": unbind})
    return jsonify({"success": False, "error": "Unbind failed", "details": unbind}), 400

@app.route('/changeemail', methods=['GET'])
def change_email():
    token, err = get_access_token_from_args(request.args)
    if err:
        return jsonify({"success": False, "error": err}), 400
    new_email = request.args.get('new_email')
    new_otp = request.args.get('new_otp')
    if not new_email or not new_otp:
        return jsonify({"success": False, "error": "new_email and new_otp required"}), 400
    # Two ways: security_code OR (current_email + otp)
    sec = request.args.get('security_code')
    cur_email = request.args.get('current_email')
    cur_otp = request.args.get('otp')
    if not sec and not (cur_email and cur_otp):
        return jsonify({"success": False, "error": "Either security_code or (current_email+otp) required"}), 400
    if sec and (cur_email or cur_otp):
        return jsonify({"success": False, "error": "Provide only one verification method"}), 400
    api = GarenaBind(token)
    # Verify identity
    if sec:
        verify = api.verify_identity(sec)
    else:
        verify = api.verify_identity_with_otp(cur_email, cur_otp)
    if verify.get('result') != 0:
        return jsonify({"success": False, "error": "Identity verification failed", "details": verify}), 400
    identity_token = verify.get('identity_token')
    if not identity_token:
        return jsonify({"success": False, "error": "No identity token", "details": verify}), 500
    # Verify OTP on new email
    otp_verify = api.verify_otp(new_otp, new_email)
    if otp_verify.get('result') != 0:
        return jsonify({"success": False, "error": "New email OTP verification failed", "details": otp_verify}), 400
    verifier = otp_verify.get('verifier_token')
    # Create rebind request
    rebind = api.create_rebind_request(identity_token, verifier, new_email)
    if rebind.get('result') == 0:
        return jsonify({"success": True, "message": "Change email request created", "data": rebind})
    return jsonify({"success": False, "error": "Change failed", "details": rebind}), 400

# ====================== ERROR HANDLERS ======================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"success": False, "error": "NOT_FOUND", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"success": False, "error": "SERVER_ERROR", "message": "Internal server error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8001))
    log_info(f'Starting Garena Account Management API on port {port}')
    app.run(host='0.0.0.0', port=port, debug=True)