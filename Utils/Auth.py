import time

from starlette.requests import Request
from starlette.responses import JSONResponse

from Utils import Redis, Configuration
from Utils.Configuration import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, API_LOCATION

bad_auth_resp = JSONResponse({"status": "Unauthorized"}, status_code=401)


async def query_endpoint(request, method, endpoint, data=None):
    session_pool = request.app.session_pool
    expiry = request.session["expires_at"]
    if time.time() + 3 * 24 * 60 * 60 >= int(expiry):
        token = await get_bearer_token(request=request, refresh=True)
    else:
        token = request.session['access_token']
    headers = dict(Authorization=f"Bearer {token}")
    async with getattr(session_pool, method)(f"{API_LOCATION}/{endpoint}", data=data, headers=headers) as response:
        return await response.json()


async def get_bearer_token(request: Request, refresh: bool = False, auth_code: str = ""):
    session_pool = request.app.session_pool

    body = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify guilds"
    }

    if refresh:
        # do we know who this is supposed to be?
        if "user_id" not in request.session:
            raise RuntimeError("No clue who you are mate")

        refresh_token = request.session["refresh_token"]
        if refresh_token is None or refresh_token is 0:
            raise RuntimeError("No refresh token available for this user!")
        body["grant_type"] = "refresh_token"
        body["refresh_token"] = refresh_token

    else:
        body["grant_type"] = "authorization_code"

    print("Fetching token...")

    async with session_pool.post(f"{API_LOCATION}/oauth2/token", data=body) as token_resp:
        token_return = await token_resp.json()

        access_token = token_return["access_token"]
        refresh_token = token_return["refresh_token"]
        expires_at = int(time.time() + token_return["expires_in"])

    # Fetch user info
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    async with session_pool.get(f"{API_LOCATION}/users/@me", headers=headers) as resp:
        user_info = await resp.json()
        user_id = user_info["id"]

    request.session["user_id"] = user_id
    request.session["refresh_token"] = refresh_token
    request.session["access_token"] = access_token
    request.session["expires_at"] = expires_at

    return access_token


# Currently, nothing ever hits this decorator, so it does nothing.
def auth_required(handler):
    async def wrapper(request: Request):
        if any(k not in request.session for k in ["user_id", "refresh_token", "access_token", "expires_at"]):  # Either the cookie expired or was tampered with
            return bad_auth_resp
        return await handler(request)

    wrapper.__name__ = handler.__name__
    return wrapper
