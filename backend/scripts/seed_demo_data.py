"""Demo data seed script for the local dev Postgres DB (saas_mvp_dev).

Drives the REAL HTTP API of the FastAPI app in-process (httpx.ASGITransport) end
to end for two demo tenants ("Umayal Agency", "ATSM Traders") -- never raw SQL
inserts for business data -- so every validation rule, GST calculation,
numbering sequence, and audit trail fires exactly as it would for a real user.

Run with:
    cd backend && ./.venv/Scripts/python.exe scripts/seed_demo_data.py

Idempotency: every creation step first tries to create via the real API; if
that fails with a conflict-shaped error, it looks up the existing record by a
natural key (phone/sku/customer+supplier id, etc.) and reuses it instead of
crashing. This lets the script be safely re-run after a partial failure
without needing to wipe the dev DB, and without ever falling back to raw SQL
writes for business data (only a read-only tenant-existence check uses SQL).

IMPORTANT: must run with ENVIRONMENT=development (set below, before any other
app import) so app/db/session.py uses the pooled engine against the real dev
DB configured in backend/.env -- never "testing" (that would only change
pooling, but is also the wrong signal -- the real safety comes from
DATABASE_URL in .env pointing at saas_mvp_dev on port 5433).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider  # noqa: E402

SHARED_PASSWORD = "Demo@12345"
TODAY = date.today()


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


async def call(
    client: AsyncClient,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    headers: dict | None = None,
    expect: tuple[int, ...] = (200, 201),
) -> Any:
    resp = await client.request(method, f"/api/v1{path}", json=json, headers=headers)
    if resp.status_code not in expect:
        raise ApiError(
            f"{method} {path} -> {resp.status_code}: {resp.text[:1500]}\nSENT: {json}",
            status_code=resp.status_code,
        )
    if resp.status_code == 204:
        return {}
    body = resp.json()
    return body.get("data", body)


async def tenant_exists(business_name: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant).where(Tenant.business_name == business_name))
        return result.scalar_one_or_none() is not None


async def find_one(client: AsyncClient, path: str, predicate: Callable[[dict], bool]) -> dict | None:
    resp = await client.get(f"/api/v1{path}")
    if resp.status_code != 200:
        return None
    body = resp.json()
    items = body.get("data", body)
    if not isinstance(items, list):
        return None
    for item in items:
        try:
            if predicate(item):
                return item
        except Exception:
            continue
    return None


async def create_or_reuse(
    create: Callable[[], Awaitable[dict]],
    find: Callable[[], Awaitable[dict | None]],
    *,
    label: str,
) -> tuple[dict, bool]:
    """Try `create()`; on any ApiError, fall back to `find()`. Returns
    (record, was_created)."""
    try:
        record = await create()
        return record, True
    except ApiError as exc:
        existing = await find()
        if existing is not None:
            print(f"[REUSE] {label} already exists, reusing id={existing.get('id')}")
            return existing, False
        print(f"[FAIL] {label}: create failed and no existing match found: {exc}")
        raise


async def reset_password_via_console_link(client: AsyncClient, email: str, new_password: str) -> None:
    """Use the dev-only ConsolePasswordRecoveryProvider outbox to set a known
    password for a user created via POST /users (which issues a random,
    unusable password + an immediate reset link, per PROMPT-004/005)."""
    before = len(ConsolePasswordRecoveryProvider.outbox)
    resp = await client.post("/api/v1/auth/forgot-password", json={"recovery_identifier": email})
    if resp.status_code != 200:
        raise ApiError(f"forgot-password for {email} -> {resp.status_code}: {resp.text[:500]}")
    if len(ConsolePasswordRecoveryProvider.outbox) <= before:
        raise ApiError(f"No recovery outbox entry appeared for {email}")
    entry = ConsolePasswordRecoveryProvider.outbox[-1]
    qs = parse_qs(urlparse(entry.reset_link).query)
    token = qs["token"][0]

    validate = await client.post("/api/v1/auth/reset-password/validate", json={"token": token})
    if validate.status_code != 200:
        raise ApiError(f"reset-password/validate for {email} -> {validate.status_code}: {validate.text[:500]}")

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": new_password, "confirm_password": new_password},
    )
    if resp.status_code != 200:
        raise ApiError(f"reset-password for {email} -> {resp.status_code}: {resp.text[:500]}")


async def create_tenant_owner(client: AsyncClient, **kwargs: Any) -> dict:
    payload = {
        "organization": {
            "business_name": kwargs["business_name"],
            "address_line1": kwargs["address_line1"],
            "city": kwargs["city"],
            "state_code": kwargs["state_code"],
            "pin_code": kwargs["pin_code"],
            "gstin": kwargs["gstin"],
        },
        "owner": {
            "phone": kwargs["owner_phone"],
            "email": kwargs["owner_email"],
            "password": SHARED_PASSWORD,
            "confirm_password": SHARED_PASSWORD,
        },
    }
    return await call(client, "POST", "/auth/sign-up", json=payload, headers=idem(), expect=(201,))


async def login(client: AsyncClient, phone: str, password: str) -> dict:
    return await call(client, "POST", "/auth/login", json={"login_identifier": phone, "password": password})


async def get_or_create_user(client: AsyncClient, *, name: str, phone: str, email: str, role: str) -> dict:
    record, created = await create_or_reuse(
        lambda: call(client, "POST", "/users", json={"name": name, "phone": phone, "email": email, "role": role}, expect=(201,)),
        lambda: find_one(client, "/users", lambda u: u.get("phone") == phone),
        label=f"user {name} ({phone})",
    )
    if created:
        await reset_password_via_console_link(client, email, SHARED_PASSWORD)
    return record


async def update_company_profile(client: AsyncClient, **updates: Any) -> dict:
    """PATCH /tenant via the real API — idempotent to re-run since it always
    reads the CURRENT row first (including its row_version) rather than
    assuming an initial state, same "drive the real HTTP API" discipline as
    every other helper in this script."""
    current = await call(client, "GET", "/tenant")
    payload = {
        key: current[key]
        for key in (
            "business_name", "gstin", "state_code", "address_line1", "city", "pin_code",
            "pan", "business_type", "phone", "email", "website",
            "bank_name", "bank_account_number", "bank_account_holder_name", "bank_ifsc",
            "bank_branch_name", "bank_account_type", "bank_upi_id",
        )
    }
    payload.update(updates)
    payload["expected_row_version"] = current["row_version"]
    return await call(client, "PATCH", "/tenant", json=payload)


async def get_or_create_uom(client: AsyncClient, code: str, name: str, precision: int = 2) -> str:
    existing = await find_one(client, "/units", lambda u: u.get("code") == code)
    if existing:
        return existing["id"]
    created = await call(client, "POST", "/units", json={"code": code, "name": name, "precision": precision}, expect=(201,))
    return created["id"]


async def get_or_create_customer(client: AsyncClient, *, phone: str, **fields: Any) -> dict:
    # Check-first: customer phone uniqueness is NOT enforced server-side (no
    # conflict on a duplicate POST, especially for B2C customers with no
    # GSTIN), so relying on create-then-fallback-on-conflict silently creates
    # duplicates on every re-run. Look up by phone first instead.
    existing = await find_one(client, "/customers", lambda c: c.get("phone") == phone)
    if existing:
        return existing
    return await call(client, "POST", "/customers", json={"phone": phone, **fields}, headers=idem(), expect=(201,))


async def get_or_create_supplier(client: AsyncClient, *, phone: str, **fields: Any) -> dict:
    existing = await find_one(client, "/suppliers", lambda s: s.get("phone") == phone)
    if existing:
        return existing
    return await call(client, "POST", "/suppliers", json={"phone": phone, **fields}, headers=idem(), expect=(201,))


async def get_or_create_product(client: AsyncClient, *, sku: str, **fields: Any) -> dict:
    record, _ = await create_or_reuse(
        lambda: call(client, "POST", "/products", json={"sku": sku, **fields}, expect=(201,)),
        lambda: find_one(client, "/products", lambda p: p.get("sku") == sku),
        label=f"product {sku}",
    )
    return record


async def ensure_conversion(client: AsyncClient, product_id: str, from_uom_id: str, to_uom_id: str, factor: float) -> None:
    try:
        await call(
            client,
            "POST",
            f"/products/{product_id}/conversions",
            json={"from_uom_id": from_uom_id, "to_uom_id": to_uom_id, "conversion_factor": factor},
            expect=(201,),
        )
    except ApiError as exc:
        print(f"[SKIP] conversion for product {product_id} already exists or failed: {exc}")


async def ensure_opening_stock(client: AsyncClient, product_id: str, uom_id: str, quantity: float) -> None:
    try:
        await call(
            client,
            "POST",
            "/inventory/opening-stock",
            json={"product_id": product_id, "quantity": quantity, "uom_id": uom_id},
            headers=idem(),
            expect=(201,),
        )
    except ApiError as exc:
        print(f"[SKIP] opening stock for product {product_id} already posted or failed: {exc}")


def amt(record: dict, *keys: str, default: float = 1000.0) -> float:
    for key in keys:
        if key in record and record[key] is not None:
            return float(record[key])
    return default


# --------------------------------------------------------------------------
# Umayal Agency (full showcase tenant)
# --------------------------------------------------------------------------


async def seed_umayal() -> dict:
    business_name = "Umayal Agency"
    report: dict[str, Any] = {"name": business_name, "users": [], "data": []}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as owner_client:
        print(f"\n=== {business_name} ===")

        if await tenant_exists(business_name):
            print("[RESUME] Tenant already exists -- resuming/completing it via the API.")
        else:
            signup = await create_tenant_owner(
                owner_client,
                business_name=business_name,
                address_line1="12 Big Bazaar Street",
                city="Madurai",
                state_code="33",
                pin_code="625001",
                gstin="33UMAYA1234A1Z5",
                owner_phone="9800000001",
                owner_email="owner@umayalagency.test",
            )
            print("sign-up ok:", signup)

        owner_login = await login(owner_client, "9800000001", SHARED_PASSWORD)
        print("owner login ok:", owner_login["user"]["id"])
        report["users"].append({"name": "Owner (Umayal Agency)", "role": "OWNER", "phone": "9800000001", "email": "owner@umayalagency.test"})

        # --- Users: 1 Manager, 2 Salespersons ---
        await get_or_create_user(owner_client, name="Karthik Raja", phone="9800000002", email="karthik.manager@umayalagency.test", role="MANAGER")
        report["users"].append({"name": "Karthik Raja", "role": "MANAGER", "phone": "9800000002", "email": "karthik.manager@umayalagency.test"})

        await get_or_create_user(owner_client, name="Priya Dharshini", phone="9800000003", email="priya.sales@umayalagency.test", role="SALESPERSON")
        report["users"].append({"name": "Priya Dharshini", "role": "SALESPERSON", "phone": "9800000003", "email": "priya.sales@umayalagency.test"})

        await get_or_create_user(owner_client, name="Manikandan S", phone="9800000004", email="mani.sales@umayalagency.test", role="SALESPERSON")
        report["users"].append({"name": "Manikandan S", "role": "SALESPERSON", "phone": "9800000004", "email": "mani.sales@umayalagency.test"})

        for phone in ("9800000002", "9800000003", "9800000004"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as vc:
                v = await login(vc, phone, SHARED_PASSWORD)
                print(f"verified login for {phone}: user_id={v['user']['id']}")

        # --- Company Profile (migration 0033) ---
        # PAN below is exactly the 10-char PAN embedded in this tenant's own
        # GSTIN ("33UMAYA1234A1Z5"[2:12] == "UMAYA1234A"), not an unrelated
        # made-up value — real GSTINs always encode the holder's PAN this way.
        await update_company_profile(
            owner_client,
            pan="UMAYA1234A",
            business_type="Super Stockist",
            phone="9800000001",
            email="owner@umayalagency.test",
            website="www.umayalagency.test",
            bank_name="HDFC Bank",
            bank_account_number="50200012345678",
            bank_account_holder_name="Umayal Agency",
            bank_ifsc="HDFC0001234",
            bank_branch_name="Madurai Main",
            bank_account_type="Current",
            bank_upi_id="umayalagency@hdfc",
        )
        report["data"].append("Company Profile: PAN/business type/contact/bank details set")

        # --- Units of measure ---
        pcs_id = await get_or_create_uom(owner_client, "PCS", "Pieces", 0)
        kg_id = await get_or_create_uom(owner_client, "KG", "Kilogram", 3)
        ltr_id = await get_or_create_uom(owner_client, "LTR", "Litre", 3)
        ctn_id = await get_or_create_uom(owner_client, "CTN", "Carton", 0)

        # --- Products ---
        product_specs = [
            dict(sku="OIL-SUN-1L", name="Sunflower Cooking Oil 1L", hsn_code="1512", gst_rate=5.00, base_uom_id=ltr_id, cost_price=110.00, selling_price=135.00, mrp=145.00),
            dict(sku="RICE-PONNI-25K", name="Ponni Rice 25Kg Bag", hsn_code="1006", gst_rate=5.00, base_uom_id=kg_id, cost_price=1050.00, selling_price=1200.00, mrp=1250.00),
            dict(sku="SOAP-LIME-100G", name="Lime Fresh Bath Soap 100g", hsn_code="3401", gst_rate=18.00, base_uom_id=pcs_id, cost_price=18.00, selling_price=25.00, mrp=28.00),
            dict(sku="BISC-GLU-100G", name="Glucose Biscuits 100g Pack", hsn_code="1905", gst_rate=12.00, base_uom_id=pcs_id, cost_price=8.00, selling_price=10.00, mrp=12.00),
            dict(sku="TEA-LEAF-500G", name="Premium Tea Leaves 500g", hsn_code="0902", gst_rate=5.00, base_uom_id=pcs_id, cost_price=210.00, selling_price=250.00, mrp=270.00),
            dict(sku="DET-POWDER-1K", name="Detergent Powder 1Kg", hsn_code="3402", gst_rate=18.00, base_uom_id=kg_id, cost_price=85.00, selling_price=110.00, mrp=120.00),
            dict(sku="SALT-IODIZED-1K", name="Iodized Salt 1Kg", hsn_code="2501", gst_rate=5.00, base_uom_id=kg_id, cost_price=18.00, selling_price=22.00, mrp=25.00),
            dict(sku="ATTA-WHEAT-5K", name="Wheat Atta 5Kg", hsn_code="1101", gst_rate=5.00, base_uom_id=kg_id, cost_price=220.00, selling_price=260.00, mrp=280.00),
        ]
        products: dict[str, dict] = {}
        for spec in product_specs:
            sku = spec.pop("sku")
            products[sku] = await get_or_create_product(owner_client, sku=sku, **spec)
            spec["sku"] = sku
        print(f"products ready: {len(products)}")

        await ensure_conversion(owner_client, products["BISC-GLU-100G"]["id"], ctn_id, pcs_id, 24)

        for spec in product_specs:
            p = products[spec["sku"]]
            await ensure_opening_stock(owner_client, p["id"], spec["base_uom_id"], 1000)
        print("opening stock ensured for all products")

        # --- Customers ---
        customers: dict[str, dict] = {}
        customers["b2b_same_state"] = await get_or_create_customer(
            owner_client, name="Sri Lakshmi Stores", owner_name="Rajendran M", phone="9800001001",
            email="srilakshmi.stores@example.test", gstin="33BCDEF5678B1Z9", state_code="33",
            address="21 Bazaar Road", city="Madurai", pincode="625002", region="South",
            credit_limit=100000, payment_terms_days=30,
        )
        customers["b2b_diff_state"] = await get_or_create_customer(
            owner_client, name="Metro Retail Karnataka", owner_name="Suresh Gowda", phone="9800001002",
            email="metro.retail.ka@example.test", gstin="29GHIJK4321C1Z2", state_code="29",
            address="55 MG Road", city="Bengaluru", pincode="560001", region="South",
            credit_limit=75000, payment_terms_days=15,
        )
        customers["b2c_1"] = await get_or_create_customer(
            owner_client, name="Anitha Kumar", owner_name="Anitha Kumar", phone="9800001003",
            email="anitha.kumar@example.test", address="8 Nehru Street", city="Madurai", pincode="625003",
        )
        customers["b2c_2"] = await get_or_create_customer(
            owner_client, name="Rajesh General Store", owner_name="Rajesh Kannan", phone="9800001004",
            email="rajesh.gs@example.test", address="3 Market Road", city="Trichy", pincode="620001",
        )
        customers["b2b_3"] = await get_or_create_customer(
            owner_client, name="Amman Traders", owner_name="Selvam K", phone="9800001005",
            email="amman.traders@example.test", gstin="33LMNOP7890D1Z6", state_code="33",
            address="17 Temple Street", city="Madurai", pincode="625004", region="South",
            credit_limit=50000, payment_terms_days=30,
        )
        print(f"customers ready: {len(customers)}")

        # --- Suppliers ---
        suppliers: dict[str, dict] = {}
        suppliers["s1"] = await get_or_create_supplier(
            owner_client, name="Yuvan Food Products", contact_person="Yuvaraj N", phone="9800002001",
            email="yuvan.foods@example.test", gstin="33QRSTU1111E1Z1", state_code="33",
            address="Industrial Estate, Phase 1", city="Madurai", pincode="625014", credit_terms_days=30,
        )
        suppliers["s2"] = await get_or_create_supplier(
            owner_client, name="Nallamani Enterprises", contact_person="Nallamani R", phone="9800002002",
            email="nallamani.ent@example.test", gstin="33VWXYZ2222F1Z4", state_code="33",
            address="45 SIDCO Estate", city="Madurai", pincode="625019", credit_terms_days=15,
        )
        suppliers["s3"] = await get_or_create_supplier(
            owner_client, name="VK Arumuga Gounder & Sons", contact_person="Arumugam V", phone="9800002003",
            email="vk.arumuga@example.test", gstin="33ABCXY3333G1Z8", state_code="33",
            address="12 Mill Road", city="Coimbatore", pincode="641001", credit_terms_days=30,
        )
        print(f"suppliers ready: {len(suppliers)}")

        oil = products["OIL-SUN-1L"]
        rice = products["RICE-PONNI-25K"]
        soap = products["SOAP-LIME-100G"]
        biscuit = products["BISC-GLU-100G"]
        tea = products["TEA-LEAF-500G"]

        # ================= SALES CHAIN =================
        # 1) Estimate -> Sales Order -> Delivery Challan -> Sales Invoice (POSTED)
        so_existing = await find_one(
            owner_client, "/sales/orders",
            lambda o: o.get("customer_id") == customers["b2b_same_state"]["id"] and o.get("source_estimate_id"),
        )
        if so_existing:
            so = await call(owner_client, "GET", f"/sales/orders/{so_existing['id']}", expect=(200,))
            print("[REUSE] sales order", so["order_number"])
        else:
            estimate = await call(
                owner_client, "POST", "/sales/estimates",
                json={
                    "customer_id": customers["b2b_same_state"]["id"],
                    "document_date": str(TODAY),
                    "valid_until_date": str(TODAY + timedelta(days=15)),
                    "notes": "Monthly stock replenishment quote",
                    "lines": [
                        {"product_id": oil["id"], "quantity": 20, "uom_id": ltr_id, "unit_price": 135.00, "discount_percent": 2},
                        {"product_id": rice["id"], "quantity": 5, "uom_id": kg_id, "unit_price": 1200.00, "discount_percent": 0},
                    ],
                },
                headers=idem(), expect=(201,),
            )
            await call(owner_client, "POST", f"/sales/estimates/{estimate['id']}/send", json={"expected_row_version": estimate["row_version"]})
            est_get = await call(owner_client, "GET", f"/sales/estimates/{estimate['id']}", expect=(200,))
            await call(owner_client, "POST", f"/sales/estimates/{estimate['id']}/accept", json={"expected_row_version": est_get["row_version"]})
            est_get = await call(owner_client, "GET", f"/sales/estimates/{estimate['id']}", expect=(200,))
            conversion = await call(
                owner_client, "POST", f"/sales/estimates/{estimate['id']}/convert-to-sales-order",
                json={"expected_row_version": est_get["row_version"]}, headers=idem(), expect=(200, 201),
            )
            so = await call(owner_client, "GET", f"/sales/orders/{conversion['sales_order_id']}", expect=(200,))
            print("created sales order", so["order_number"])

        if so["status"] == "DRAFT":
            await call(owner_client, "POST", f"/sales/orders/{so['id']}/confirm", json={"expected_row_version": so["row_version"]})
            so = await call(owner_client, "GET", f"/sales/orders/{so['id']}", expect=(200,))

        dc_existing = await find_one(owner_client, "/sales/delivery-challans", lambda d: d.get("source_sales_order_id") == so["id"])
        if dc_existing:
            dc = await call(owner_client, "GET", f"/sales/delivery-challans/{dc_existing['id']}", expect=(200,))
            print("[REUSE] delivery challan", dc["challan_number"])
        else:
            dc = await call(
                owner_client, "POST", "/sales/delivery-challans",
                json={
                    "sales_order_id": so["id"],
                    "challan_date": str(TODAY),
                    "notes": "First partial delivery",
                    "lines": [{"sales_order_line_id": line["id"], "quantity": line["quantity"]} for line in so["lines"]],
                },
                headers=idem(), expect=(201,),
            )
            print("created delivery challan", dc["challan_number"])

        if dc["status"] != "CONFIRMED":
            dc = await call(owner_client, "POST", f"/sales/delivery-challans/{dc['id']}/confirm", json={"expected_row_version": dc["row_version"]}, headers=idem(), expect=(200,))
        print("delivery challan status:", dc["status"])

        chain_inv_existing = await find_one(owner_client, "/sales/invoices", lambda i: i.get("customer_id") == customers["b2b_same_state"]["id"])
        if chain_inv_existing:
            chain_invoice = await call(owner_client, "GET", f"/sales/invoices/{chain_inv_existing['id']}", expect=(200,))
            print("[REUSE] chain invoice", chain_invoice.get("invoice_number"))
        else:
            chain_invoice = await call(
                owner_client, "POST", f"/sales/delivery-challans/{dc['id']}/create-invoice",
                json={
                    "invoice_date": str(TODAY),
                    "notes": "Invoice against delivery challan",
                    "lines": [
                        {"source_delivery_challan_line_id": line["id"], "quantity": line["current_delivery_quantity"]}
                        for line in dc["lines"]
                    ],
                },
                headers=idem(), expect=(201,),
            )
            print("created chain invoice", chain_invoice.get("invoice_number"))

        if chain_invoice["status"] == "DRAFT":
            chain_invoice = await call(
                owner_client, "POST", f"/sales/invoices/{chain_invoice['id']}/post",
                json={"expected_row_version": chain_invoice["row_version"]}, headers=idem(), expect=(200,),
            )
        print("chain invoice status:", chain_invoice["status"], chain_invoice.get("invoice_number"))

        # 2) DIRECT Sales Invoice (posted)
        direct_inv_existing = await find_one(owner_client, "/sales/invoices", lambda i: i.get("customer_id") == customers["b2b_diff_state"]["id"])
        if direct_inv_existing:
            direct_invoice = await call(owner_client, "GET", f"/sales/invoices/{direct_inv_existing['id']}", expect=(200,))
            print("[REUSE] direct invoice", direct_invoice.get("invoice_number"))
        else:
            direct_invoice = await call(
                owner_client, "POST", "/sales/invoices",
                json={
                    "customer_id": customers["b2b_diff_state"]["id"],
                    "invoice_date": str(TODAY),
                    "notes": "Direct cash-and-carry sale",
                    "lines": [
                        {"product_id": soap["id"], "quantity": 50, "uom_id": pcs_id, "unit_price": 25.00},
                        {"product_id": biscuit["id"], "quantity": 100, "uom_id": pcs_id, "unit_price": 10.00},
                    ],
                },
                headers=idem(), expect=(201,),
            )
            print("created direct invoice", direct_invoice.get("invoice_number"))

        if direct_invoice["status"] == "DRAFT":
            direct_invoice = await call(
                owner_client, "POST", f"/sales/invoices/{direct_invoice['id']}/post",
                json={"expected_row_version": direct_invoice["row_version"]}, headers=idem(), expect=(200,),
            )
        print("direct invoice status:", direct_invoice["status"], direct_invoice.get("invoice_number"))

        direct_invoice_full = await call(owner_client, "GET", f"/sales/invoices/{direct_invoice['id']}", expect=(200,))
        soap_line = next(line for line in direct_invoice_full["lines"] if line["product_id"] == soap["id"])
        biscuit_line = next(line for line in direct_invoice_full["lines"] if line["product_id"] == biscuit["id"])

        # 3) Sales Return against the direct invoice
        sr_existing = await find_one(owner_client, "/sales/returns", lambda r: r.get("source_invoice_id") == direct_invoice["id"])
        if sr_existing:
            sales_return = await call(owner_client, "GET", f"/sales/returns/{sr_existing['id']}", expect=(200,))
            print("[REUSE] sales return", sales_return.get("return_number", sales_return["id"]))
        else:
            sales_return = await call(
                owner_client, "POST", "/sales/returns",
                json={
                    "source_invoice_id": direct_invoice["id"],
                    "return_date": str(TODAY),
                    "return_reason": "DAMAGED",
                    "notes": "5 units damaged in transit",
                    "lines": [{"source_invoice_line_id": soap_line["id"], "quantity": 5}],
                },
                headers=idem(), expect=(201,),
            )
            print("created sales return", sales_return.get("id"))

        if sales_return["status"] == "DRAFT":
            sales_return = await call(
                owner_client, "POST", f"/sales/returns/{sales_return['id']}/confirm",
                json={"expected_row_version": sales_return["row_version"]}, headers=idem(), expect=(200,),
            )
        print("sales return status:", sales_return["status"])

        # 4) Credit Note against the direct invoice
        cn_existing = await find_one(
            owner_client, "/sales/credit-debit-notes",
            lambda n: n.get("source_invoice_id") == direct_invoice["id"] and n.get("note_type") == "CREDIT_NOTE",
        )
        if cn_existing:
            credit_note = await call(owner_client, "GET", f"/sales/credit-debit-notes/{cn_existing['id']}", expect=(200,))
            print("[REUSE] credit note", credit_note.get("note_number", credit_note["id"]))
        else:
            credit_note = await call(
                owner_client, "POST", "/sales/credit-debit-notes",
                json={
                    "source_invoice_id": direct_invoice["id"],
                    "note_type": "CREDIT_NOTE",
                    "note_date": str(TODAY),
                    "reason": "Post-sale price correction for bulk order",
                    "lines": [{"source_invoice_line_id": biscuit_line["id"], "quantity": 10}],
                },
                headers=idem(), expect=(201,),
            )
            print("created credit note", credit_note.get("id"))

        if credit_note["status"] == "DRAFT":
            credit_note = await call(
                owner_client, "POST", f"/sales/credit-debit-notes/{credit_note['id']}/post",
                json={"expected_row_version": credit_note["row_version"]}, headers=idem(), expect=(200,),
            )
        print("credit note status:", credit_note["status"])

        # ================= PURCHASE CHAIN =================
        po_existing = await find_one(owner_client, "/purchase/orders", lambda o: o.get("supplier_id") == suppliers["s1"]["id"])
        if po_existing:
            po = await call(owner_client, "GET", f"/purchase/orders/{po_existing['id']}", expect=(200,))
            print("[REUSE] purchase order", po.get("order_number", po["id"]))
        else:
            po = await call(
                owner_client, "POST", "/purchase/orders",
                json={
                    "supplier_id": suppliers["s1"]["id"],
                    "document_date": str(TODAY),
                    "supplier_reference": "YFP-QTN-2026-09",
                    "expected_delivery_date": str(TODAY + timedelta(days=7)),
                    "payment_terms": "Net 30",
                    "delivery_terms": "FOB Madurai",
                    "lines": [
                        {"product_id": oil["id"], "quantity": 100, "uom_id": ltr_id, "unit_price": 110.00},
                        {"product_id": tea["id"], "quantity": 30, "uom_id": pcs_id, "unit_price": 210.00},
                    ],
                },
                headers=idem(), expect=(201,),
            )
            print("created purchase order", po.get("id"))

        if po["status"] == "DRAFT":
            await call(owner_client, "POST", f"/purchase/orders/{po['id']}/confirm", json={"expected_row_version": po["row_version"]})
        po = await call(owner_client, "GET", f"/purchase/orders/{po['id']}", expect=(200,))

        gr_existing = await find_one(owner_client, "/purchase/goods-receipts", lambda g: g.get("source_purchase_order_id") == po["id"])
        if gr_existing:
            gr = await call(owner_client, "GET", f"/purchase/goods-receipts/{gr_existing['id']}", expect=(200,))
            print("[REUSE] goods receipt", gr.get("receipt_number", gr["id"]))
        else:
            gr = await call(
                owner_client, "POST", "/purchase/goods-receipts",
                json={
                    "purchase_order_id": po["id"],
                    "document_date": str(TODAY),
                    "supplier_delivery_note": "DN-8891",
                    "lines": [{"purchase_order_line_id": line["id"], "quantity": line["quantity"]} for line in po["lines"]],
                },
                headers=idem(), expect=(201,),
            )
            print("created goods receipt", gr.get("id"))

        if gr["status"] != "CONFIRMED":
            gr = await call(owner_client, "POST", f"/purchase/goods-receipts/{gr['id']}/confirm", json={"expected_row_version": gr["row_version"]}, headers=idem(), expect=(200,))
        print("goods receipt status:", gr["status"])

        pinv_existing = await find_one(owner_client, "/purchase/invoices", lambda i: i.get("supplier_id") == suppliers["s1"]["id"])
        if pinv_existing:
            p_invoice = await call(owner_client, "GET", f"/purchase/invoices/{pinv_existing['id']}", expect=(200,))
            print("[REUSE] purchase invoice", p_invoice.get("invoice_number", p_invoice["id"]))
        else:
            p_invoice = await call(
                owner_client, "POST", f"/purchase/goods-receipts/{gr['id']}/create-invoice",
                json={
                    "document_date": str(TODAY),
                    "supplier_invoice_number": "YFP-INV-3301",
                    "supplier_invoice_date": str(TODAY),
                    "due_date": str(TODAY + timedelta(days=30)),
                    "lines": [{"source_goods_receipt_line_id": line["id"], "quantity": line["quantity"]} for line in gr["lines"]],
                },
                headers=idem(), expect=(201,),
            )
            print("created purchase invoice", p_invoice.get("id"))

        if p_invoice["status"] == "DRAFT":
            p_invoice = await call(
                owner_client, "POST", f"/purchase/invoices/{p_invoice['id']}/post",
                json={"expected_row_version": p_invoice["row_version"]}, headers=idem(), expect=(200,),
            )
        print("purchase invoice status:", p_invoice["status"], p_invoice.get("invoice_number"))

        p_invoice_full = await call(owner_client, "GET", f"/purchase/invoices/{p_invoice['id']}", expect=(200,))
        oil_pline = next(line for line in p_invoice_full["lines"] if line["product_id"] == oil["id"])

        pr_existing = await find_one(owner_client, "/purchase/returns", lambda r: r.get("source_purchase_invoice_id") == p_invoice["id"])
        if pr_existing:
            purchase_return = await call(owner_client, "GET", f"/purchase/returns/{pr_existing['id']}", expect=(200,))
            print("[REUSE] purchase return", purchase_return.get("id"))
        else:
            purchase_return = await call(
                owner_client, "POST", "/purchase/returns",
                json={
                    "source_purchase_invoice_id": p_invoice["id"],
                    "document_date": str(TODAY),
                    "return_reason": "QUALITY_ISSUE",
                    "notes": "10 litres below quality standard",
                    "lines": [{"source_purchase_invoice_line_id": oil_pline["id"], "quantity": 10}],
                },
                headers=idem(), expect=(201,),
            )
            print("created purchase return", purchase_return.get("id"))

        if purchase_return["status"] == "DRAFT":
            purchase_return = await call(
                owner_client, "POST", f"/purchase/returns/{purchase_return['id']}/confirm",
                json={"expected_row_version": purchase_return["row_version"]}, headers=idem(), expect=(200,),
            )
        print("purchase return status:", purchase_return["status"])

        # ================= PAYMENTS =================
        receipt_amount = amt(direct_invoice, "grand_total")
        cr_existing = await find_one(owner_client, "/customer-receipts", lambda r: r.get("customer_id") == customers["b2b_diff_state"]["id"])
        if cr_existing:
            receipt = await call(owner_client, "GET", f"/customer-receipts/{cr_existing['id']}", expect=(200,))
            print("[REUSE] customer receipt", receipt.get("id"))
        else:
            receipt = await call(
                owner_client, "POST", "/customer-receipts",
                json={
                    "customer_id": customers["b2b_diff_state"]["id"],
                    "payment_date": str(TODAY),
                    "payment_method": "BANK_TRANSFER",
                    "amount": receipt_amount,
                    "reference_number": "NEFT-990011",
                    "client_transaction_id": str(uuid.uuid4()),
                    "allocations": [{"invoice_id": direct_invoice["id"], "allocated_amount": receipt_amount}],
                },
                headers=idem(), expect=(201,),
            )
            print("created customer receipt", receipt.get("id"))

        if receipt["status"] == "DRAFT":
            receipt = await call(
                owner_client, "POST", f"/customer-receipts/{receipt['id']}/post",
                json={"expected_row_version": receipt["row_version"]}, headers=idem(), expect=(200,),
            )
        print("customer receipt status:", receipt["status"])

        payment_amount = amt(p_invoice, "grand_total")
        sp_existing = await find_one(owner_client, "/supplier-payments", lambda p: p.get("supplier_id") == suppliers["s1"]["id"])
        if sp_existing:
            payment = await call(owner_client, "GET", f"/supplier-payments/{sp_existing['id']}", expect=(200,))
            print("[REUSE] supplier payment", payment.get("id"))
        else:
            payment = await call(
                owner_client, "POST", "/supplier-payments",
                json={
                    "supplier_id": suppliers["s1"]["id"],
                    "payment_date": str(TODAY),
                    "payment_method": "BANK_TRANSFER",
                    "amount": payment_amount,
                    "reference_number": "NEFT-770022",
                    "client_transaction_id": str(uuid.uuid4()),
                    "allocations": [{"invoice_id": p_invoice["id"], "allocated_amount": payment_amount}],
                },
                headers=idem(), expect=(201,),
            )
            print("created supplier payment", payment.get("id"))

        if payment["status"] == "DRAFT":
            payment = await call(
                owner_client, "POST", f"/supplier-payments/{payment['id']}/post",
                json={"expected_row_version": payment["row_version"]}, headers=idem(), expect=(200,),
            )
        print("supplier payment status:", payment["status"])

        # ================= PAYROLL =================
        payroll_summary = "not attempted"
        try:
            # Check-first: EmployeeListItem has no "mobile" field, and employee
            # creation does not conflict on a duplicate mobile number, so a
            # create-then-fallback pattern would silently duplicate employees
            # on every re-run. Match by full_name (unique enough for this seed).
            emp1 = await find_one(owner_client, "/employees", lambda e: e.get("full_name") == "Selvi Ramasamy")
            if not emp1:
                emp1 = await call(owner_client, "POST", "/employees", json={
                    "full_name": "Selvi Ramasamy", "mobile": "9800003001", "email": "selvi.emp@umayalagency.test",
                    "date_of_joining": str(TODAY - timedelta(days=200)), "department": "Sales",
                    "designation": "Sales Executive", "employment_type": "FULL_TIME",
                }, expect=(201,))
            emp2 = await find_one(owner_client, "/employees", lambda e: e.get("full_name") == "Muthu Vel")
            if not emp2:
                emp2 = await call(owner_client, "POST", "/employees", json={
                    "full_name": "Muthu Vel", "mobile": "9800003002", "email": "muthu.emp@umayalagency.test",
                    "date_of_joining": str(TODAY - timedelta(days=400)), "department": "Warehouse",
                    "designation": "Store Keeper", "employment_type": "FULL_TIME",
                }, expect=(201,))

            comps = await call(owner_client, "GET", "/salary-components", expect=(200,))
            comp_list = comps if isinstance(comps, list) else comps.get("items", [])
            basic = next((c for c in comp_list if "BASIC" in (c.get("code") or "").upper() or "BASIC" in (c.get("name") or "").upper()), comp_list[0])
            hra = next((c for c in comp_list if "HRA" in (c.get("code") or "").upper() or "HRA" in (c.get("name") or "").upper()), comp_list[min(1, len(comp_list) - 1)])

            for emp in (emp1, emp2):
                try:
                    await call(
                        owner_client, "POST", f"/employees/{emp['id']}/salary-structures",
                        json={
                            "effective_from": str(TODAY - timedelta(days=180)),
                            "lines": [
                                {"component_id": basic["id"], "calculation_type": "FIXED_AMOUNT", "amount": 18000.00},
                                {"component_id": hra["id"], "calculation_type": "FIXED_AMOUNT", "amount": 5000.00},
                            ],
                        },
                        expect=(201,),
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort idempotent skip (unique constraint may raise a raw DB error, not a clean ApiError)
                    print(f"[SKIP] salary structure for {emp['id']} may already exist: {exc}")

            period_label = TODAY.strftime("%Y-%m")  # payroll_period.period_label is VARCHAR(10)
            period, _ = await create_or_reuse(
                lambda: call(owner_client, "POST", "/payroll/periods", json={
                    "period_label": period_label, "start_date": str(TODAY.replace(day=1)), "end_date": str(TODAY),
                }, expect=(201,)),
                lambda: find_one(owner_client, "/payroll/periods", lambda p: p.get("period_label") == period_label),
                label=f"payroll period {period_label}",
            )

            for emp in (emp1, emp2):
                try:
                    await call(
                        owner_client, "POST", "/attendance",
                        json={"employee_id": emp["id"], "attendance_date": str(TODAY - timedelta(days=1)), "status": "PRESENT"},
                        expect=(201,),
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort idempotent skip
                    print(f"[SKIP] attendance for {emp['id']} may already exist: {exc}")

            run_existing = await find_one(owner_client, "/payroll/runs", lambda r: r.get("payroll_period_id") == period["id"])
            if run_existing:
                run = await call(owner_client, "GET", f"/payroll/runs/{run_existing['id']}", expect=(200,))
                print("[REUSE] payroll run", run.get("id"))
            else:
                run = await call(owner_client, "POST", "/payroll/runs", json={"payroll_period_id": period["id"]}, headers=idem(), expect=(201,))
                print("created payroll run", run.get("id"))

            if run["status"] == "DRAFT":
                run = await call(owner_client, "POST", f"/payroll/runs/{run['id']}/calculate", json={"expected_row_version": run["row_version"]}, expect=(200,))
            if run["status"] == "CALCULATED":
                run = await call(
                    owner_client, "POST", f"/payroll/runs/{run['id']}/finalize",
                    json={"expected_row_version": run["row_version"]}, headers=idem(), expect=(200,),
                )
            payroll_summary = f"Payroll run for period {period_label}: status={run.get('status')} (2 employees)"
            print("payroll run status:", run.get("status"))
        except Exception as exc:  # noqa: BLE001 - payroll is best-effort; never let it abort the rest of the seed
            payroll_summary = f"SKIPPED / FAILED: {exc}"
            print("[WARN] Payroll seeding failed, continuing:", exc)

        # --- Verification ---
        cust_list = await call(owner_client, "GET", "/customers", expect=(200,))
        active_cust_count = sum(1 for c in cust_list if c.get("status", "ACTIVE") == "ACTIVE")
        inv_list = await call(owner_client, "GET", "/sales/invoices", expect=(200,))
        pinv_list = await call(owner_client, "GET", "/purchase/invoices", expect=(200,))

        report["data"] = [
            f"Customers: {[c['name'] for c in customers.values()]}",
            f"Suppliers: {[s['name'] for s in suppliers.values()]}",
            f"Products: {[p['name'] for p in products.values()]}",
            f"Chain Sales Invoice (Estimate->Order->DC->Invoice): {chain_invoice.get('invoice_number')} {chain_invoice['status']}",
            f"Direct Sales Invoice: {direct_invoice.get('invoice_number')} {direct_invoice['status']}",
            f"Sales Return {sales_return['status']} against {direct_invoice.get('invoice_number')}",
            f"Credit Note {credit_note['status']} against {direct_invoice.get('invoice_number')}",
            f"Purchase Order -> Goods Receipt -> Purchase Invoice: {p_invoice.get('invoice_number', p_invoice.get('id'))} {p_invoice['status']}",
            f"Purchase Return {purchase_return['status']} (10L oil, quality issue)",
            f"Customer Receipt {receipt['status']} (id {receipt.get('id')}) against {direct_invoice.get('invoice_number')}",
            f"Supplier Payment {payment['status']} (id {payment.get('id')}) against {p_invoice.get('invoice_number', p_invoice.get('id'))}",
            f"Payroll: {payroll_summary}",
            f"Verification counts -- active customers: {active_cust_count} (total incl. inactive: {len(cust_list)}), sales invoices: {len(inv_list)}, purchase invoices: {len(pinv_list)}",
        ]

    return report


# --------------------------------------------------------------------------
# ATSM Traders (lighter tenant)
# --------------------------------------------------------------------------


async def seed_atsm() -> dict:
    business_name = "ATSM Traders"
    report: dict[str, Any] = {"name": business_name, "users": [], "data": []}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as owner_client:
        print(f"\n=== {business_name} ===")

        if await tenant_exists(business_name):
            print("[RESUME] Tenant already exists -- resuming/completing it via the API.")
        else:
            signup = await create_tenant_owner(
                owner_client,
                business_name=business_name,
                address_line1="90 Commercial Street",
                city="Bengaluru",
                state_code="29",
                pin_code="560002",
                gstin="29ATSMT4321A1Z7",
                owner_phone="9800002101",
                owner_email="owner@atsmtraders.test",
            )
            print("sign-up ok:", signup)

        owner_login = await login(owner_client, "9800002101", SHARED_PASSWORD)
        print("owner login ok:", owner_login["user"]["id"])
        report["users"].append({"name": "Owner (ATSM Traders)", "role": "OWNER", "phone": "9800002101", "email": "owner@atsmtraders.test"})

        await get_or_create_user(owner_client, name="Divya Shree", phone="9800002102", email="divya.sales@atsmtraders.test", role="SALESPERSON")
        report["users"].append({"name": "Divya Shree", "role": "SALESPERSON", "phone": "9800002102", "email": "divya.sales@atsmtraders.test"})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as vc:
            v = await login(vc, "9800002102", SHARED_PASSWORD)
            print(f"verified login for 9800002102: user_id={v['user']['id']}")

        # --- Company Profile (migration 0033) ---
        # PAN below is the 10-char PAN embedded in this tenant's own GSTIN
        # ("29ATSMT4321A1Z7"[2:12] == "ATSMT4321A"), same pattern as Umayal
        # Agency above.
        await update_company_profile(
            owner_client,
            pan="ATSMT4321A",
            business_type="Distributor",
            phone="9800002101",
            email="owner@atsmtraders.test",
            website="www.atsmtraders.test",
            bank_name="ICICI Bank",
            bank_account_number="602345678901",
            bank_account_holder_name="ATSM Traders",
            bank_ifsc="ICIC0006023",
            bank_branch_name="Commercial Street",
            bank_account_type="Current",
            bank_upi_id="atsmtraders@icici",
        )
        report["data"].append("Company Profile: PAN/business type/contact/bank details set")

        pcs_id = await get_or_create_uom(owner_client, "PCS", "Pieces", 0)

        product_specs = [
            dict(sku="ATSM-OIL-1L", name="Groundnut Cooking Oil 1L", hsn_code="1508", gst_rate=5.00, base_uom_id=pcs_id, cost_price=150.00, selling_price=175.00, mrp=185.00),
            dict(sku="ATSM-SOAP-75G", name="Sandal Soap 75g", hsn_code="3401", gst_rate=18.00, base_uom_id=pcs_id, cost_price=22.00, selling_price=30.00, mrp=32.00),
            dict(sku="ATSM-TEA-250G", name="Masala Tea 250g", hsn_code="0902", gst_rate=5.00, base_uom_id=pcs_id, cost_price=95.00, selling_price=120.00, mrp=130.00),
        ]
        products: dict[str, dict] = {}
        for spec in product_specs:
            sku = spec.pop("sku")
            products[sku] = await get_or_create_product(owner_client, sku=sku, **spec)
            await ensure_opening_stock(owner_client, products[sku]["id"], spec["base_uom_id"], 500)
            spec["sku"] = sku
        print(f"products ready: {len(products)}")

        customers: dict[str, dict] = {}
        customers["b2b"] = await get_or_create_customer(
            owner_client, name="Karnataka Kirana Mart", owner_name="Chandru Reddy", phone="9800004001",
            email="kk.mart@example.test", gstin="29PQRXY6789H1Z0", state_code="29",
            address="14 Commercial Street", city="Bengaluru", pincode="560003",
        )
        customers["b2c"] = await get_or_create_customer(
            owner_client, name="Manjunath K", owner_name="Manjunath K", phone="9800004002",
            email="manjunath.k@example.test", address="27 Residency Road", city="Bengaluru", pincode="560004",
        )
        print(f"customers ready: {len(customers)}")

        suppliers: dict[str, dict] = {}
        suppliers["s1"] = await get_or_create_supplier(
            owner_client, name="Deccan Wholesale Foods", contact_person="Praveen Kumar", phone="9800005001",
            email="deccan.wholesale@example.test", gstin="29LMNAB1122K1Z9", state_code="29",
            address="Industrial Layout, Peenya", city="Bengaluru", pincode="560058", credit_terms_days=15,
        )
        suppliers["s2"] = await get_or_create_supplier(
            owner_client, name="Bangalore Agro Traders", contact_person="Lakshmi Devi", phone="9800005002",
            email="blr.agro@example.test", gstin="29CDEFG3344L1Z3", state_code="29",
            address="Yeshwanthpur Market", city="Bengaluru", pincode="560022", credit_terms_days=30,
        )
        print(f"suppliers ready: {len(suppliers)}")

        oil = products["ATSM-OIL-1L"]
        soap = products["ATSM-SOAP-75G"]

        direct_inv_existing = await find_one(owner_client, "/sales/invoices", lambda i: i.get("customer_id") == customers["b2b"]["id"])
        if direct_inv_existing:
            direct_invoice = await call(owner_client, "GET", f"/sales/invoices/{direct_inv_existing['id']}", expect=(200,))
            print("[REUSE] ATSM direct invoice", direct_invoice.get("invoice_number"))
        else:
            direct_invoice = await call(
                owner_client, "POST", "/sales/invoices",
                json={
                    "customer_id": customers["b2b"]["id"],
                    "invoice_date": str(TODAY),
                    "notes": "Direct sale",
                    "lines": [
                        {"product_id": oil["id"], "quantity": 20, "uom_id": pcs_id, "unit_price": 175.00},
                        {"product_id": soap["id"], "quantity": 40, "uom_id": pcs_id, "unit_price": 30.00},
                    ],
                },
                headers=idem(), expect=(201,),
            )
            print("created ATSM direct invoice", direct_invoice.get("invoice_number"))

        if direct_invoice["status"] == "DRAFT":
            direct_invoice = await call(
                owner_client, "POST", f"/sales/invoices/{direct_invoice['id']}/post",
                json={"expected_row_version": direct_invoice["row_version"]}, headers=idem(), expect=(200,),
            )
        print("ATSM direct invoice status:", direct_invoice["status"], direct_invoice.get("invoice_number"))

        pinv_existing = await find_one(owner_client, "/purchase/invoices", lambda i: i.get("supplier_id") == suppliers["s1"]["id"])
        if pinv_existing:
            p_invoice = await call(owner_client, "GET", f"/purchase/invoices/{pinv_existing['id']}", expect=(200,))
            print("[REUSE] ATSM purchase invoice", p_invoice.get("invoice_number", p_invoice["id"]))
        else:
            p_invoice = await call(
                owner_client, "POST", "/purchase/invoices",
                json={
                    "supplier_id": suppliers["s1"]["id"],
                    "document_date": str(TODAY),
                    "supplier_invoice_number": "DWF-INV-501",
                    "lines": [{"product_id": oil["id"], "quantity": 50, "uom_id": pcs_id, "unit_price": 150.00}],
                },
                headers=idem(), expect=(201,),
            )
            print("created ATSM purchase invoice", p_invoice.get("id"))

        if p_invoice["status"] == "DRAFT":
            p_invoice = await call(
                owner_client, "POST", f"/purchase/invoices/{p_invoice['id']}/post",
                json={"expected_row_version": p_invoice["row_version"]}, headers=idem(), expect=(200,),
            )
        print("ATSM purchase invoice status:", p_invoice["status"], p_invoice.get("invoice_number"))

        payments_note = "skipped (time-boxed per task scope for the smaller tenant)"

        cust_list = await call(owner_client, "GET", "/customers", expect=(200,))
        active_cust_count = sum(1 for c in cust_list if c.get("status", "ACTIVE") == "ACTIVE")
        inv_list = await call(owner_client, "GET", "/sales/invoices", expect=(200,))
        pinv_list = await call(owner_client, "GET", "/purchase/invoices", expect=(200,))

        report["data"] = [
            f"Customers: {[c['name'] for c in customers.values()]}",
            f"Suppliers: {[s['name'] for s in suppliers.values()]}",
            f"Products: {[p['name'] for p in products.values()]}",
            f"Direct Sales Invoice: {direct_invoice.get('invoice_number')} {direct_invoice['status']}",
            f"Direct Purchase Invoice: {p_invoice.get('invoice_number', p_invoice.get('id'))} {p_invoice['status']}",
            f"Payments: {payments_note}",
            "Payroll: skipped for this tenant per task scope",
            f"Verification counts -- active customers: {active_cust_count} (total incl. inactive: {len(cust_list)}), sales invoices: {len(inv_list)}, purchase invoices: {len(pinv_list)}",
        ]

    return report


async def main() -> None:
    assert os.environ["ENVIRONMENT"] == "development", "Refusing to run: ENVIRONMENT must be 'development'"
    reset_rate_limits()

    r1 = await seed_umayal()
    r2 = await seed_atsm()

    print("\n\n================ SEED SUMMARY ================")
    for r in (r1, r2):
        print(f"\n--- {r['name']} ---")
        print("Users:")
        for u in r["users"]:
            print(f"  {u['name']} | {u['role']} | phone={u['phone']} | email={u['email']} | password={SHARED_PASSWORD}")
        print("Data:")
        for line in r["data"]:
            print(f"  - {line}")


if __name__ == "__main__":
    asyncio.run(main())
