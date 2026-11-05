import time

import requests

NET_WORTH_PATH = "/transactions/net-worth/"
MANUAL_PATH = "/transactions/net-worth/manual"
RETRIES = 3
TIMEOUT = 30


class ApiError(Exception):

    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class MondayCallClient:

    def __init__(self, base_url: str, token: str, session=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session = session or requests.Session()

    def list_manual_items(self) -> list:
        return self._request("GET", NET_WORTH_PATH).get("manual", [])

    def create_manual_item(self, payload: dict) -> dict:
        return self._request("POST", MANUAL_PATH, payload)

    def update_manual_item(self, item_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"{MANUAL_PATH}/{item_id}", payload)

    def _request(self, method: str, path: str, payload=None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"X-Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        last_error = None
        for attempt in range(RETRIES):
            try:
                response = self.session.request(
                    method, url, json=payload, headers=headers, timeout=TIMEOUT
                )
            except requests.RequestException as error:
                last_error = ApiError(0, str(error))
            else:
                if response.status_code < 500:
                    return _parse(response)
                last_error = ApiError(response.status_code, response.text[:300])
            time.sleep(2**attempt)
        raise last_error


def _parse(response) -> dict:
    if response.status_code >= 400:
        raise ApiError(response.status_code, _detail(response))
    if not response.content:
        return {}
    return response.json()


def _detail(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        code = body.get("code") or body.get("message")
        if code:
            return str(code)
    return str(body)[:300]
