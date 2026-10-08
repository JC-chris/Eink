"""Client voor de cloud-API die de webinterface gebruikt (met het token van het basisstation)."""

from collections.abc import Callable

import httpx

from .config import Config

ClientFactory = Callable[[Config], httpx.Client]


def default_client_factory(config: Config) -> httpx.Client:
    return httpx.Client(base_url=config.server, headers={"Authorization": f"Bearer {config.token}"}, timeout=15)


class CloudError(Exception):
    pass


class Cloud:
    def __init__(self, client: httpx.Client):
        self.client = client

    def _call(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            resp = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise CloudError(f"cloud niet bereikbaar: {exc}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text
            if isinstance(detail, list):  # validatiefouten van FastAPI
                detail = "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail)
            raise CloudError(str(detail or f"fout {resp.status_code}"))
        return resp

    def store(self) -> dict:
        return self._call("GET", "/v1/basestation/store").json()

    def set_price_source(self, source: str) -> dict:
        return self._call("PUT", "/v1/basestation/store/settings", json={"price_source": source}).json()

    def display_types(self) -> list[dict]:
        return self._call("GET", "/v1/basestation/display-types").json()

    def products(self) -> list[dict]:
        return self._call("GET", "/v1/basestation/store/products").json()

    def upsert_product(self, sku: str, body: dict) -> dict:
        return self._call("PUT", f"/v1/basestation/store/products/{sku}", json=body).json()

    def labels(self) -> list[dict]:
        return self._call("GET", "/v1/basestation/store/labels").json()

    def register_label(self, label_id: str, display_type: str) -> dict:
        return self._call("POST", "/v1/basestation/store/labels", json={"label_id": label_id, "display_type": display_type}).json()

    def link_label(self, label_id: str, sku: str | None) -> dict:
        return self._call("PUT", f"/v1/basestation/store/labels/{label_id}/product", json={"sku": sku}).json()

    def refresh_label(self, label_id: str) -> dict:
        return self._call("POST", f"/v1/basestation/store/labels/{label_id}/refresh").json()

    def import_prices(self, filename: str, data: bytes, mapping: dict[str, str] | None, dry_run: bool,
                      default_unit: str = "st", source: str = "upload") -> dict:
        import base64

        body = {"filename": filename, "content_b64": base64.b64encode(data).decode(), "mapping": mapping,
                "dry_run": dry_run, "default_unit": default_unit}
        return self._call("POST", "/v1/basestation/store/products:import", params={"source": source}, json=body).json()

    def preview(self, label_id: str) -> bytes:
        return self._call("GET", f"/v1/basestation/store/labels/{label_id}/preview.png").content
