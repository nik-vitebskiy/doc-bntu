import json, os, shutil, uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .models import SessionLocal, Organization, Contract, OrderItem, AppUser, AdditionalAgreement, Application, Faculty
from .services.import_service import import_xlsx
from .services.document_service import render_agreement
from .services.organization_service import attach_scan, compare_agreement_order, create_contract, create_organization, delete_item, register_additional_agreement, registry as get_registry, save_item, update_contract, update_organization
from .services.auth_service import authenticate, ensure_admin, ensure_head
from .services.application_service import application_registry, attach_application_scan, create_application, save_application_item, update_application
from .services.audit_service import AuditActor
from .services.document_status_service import StatusTransitionError, allowed_status_transitions, change_agreement_status, change_application_status, change_contract_status
from .services.status_service import order_change_class, status_class, status_label
from .template_builder import make_template

Path("data").mkdir(exist_ok=True); Path("uploads").mkdir(exist_ok=True)
app = FastAPI(title="Кадровый заказ")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
views = Jinja2Templates(directory="app/views")
views.env.filters["fromjson"] = json.loads


views.env.filters["document_status"] = status_label
views.env.filters["status_class"] = status_class
views.env.filters["order_change_class"] = order_change_class
views.env.globals["allowed_status_transitions"] = allowed_status_transitions


def nav_is_active(request: Request, section: str) -> bool:
    """Keep sidebar selection correct for list and nested resource routes."""
    path = request.url.path
    prefixes = {
        "organizations": ("/organizations",),
        "applications": ("/applications",),
        "contracts": ("/contracts", "/additional-agreements"),
        "documents": ("/documents",),
    }
    return (section == "organizations" and path == "/") or path.startswith(prefixes[section])


views.env.globals["nav_is_active"] = nav_is_active

def db(): return SessionLocal()
def audit_actor(request: Request):
    client_ip = request.client.host if request.client else None
    return AuditActor(request.state.user.id, client_ip)
def urgency(end):
    if not end: return "neutral"
    days = (end - date.today()).days
    return "danger" if days <= 30 else "warning" if days <= 90 else "success"
views.env.globals["urgency"] = urgency

@app.on_event("startup")
def startup():
    make_template()
    s = db(); ensure_admin(s); ensure_head(s); s.close()

@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.url.path.startswith(("/static", "/login")):
        return await call_next(request)
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    s = db(); user = s.get(AppUser, user_id); s.close()
    if not user or not user.is_active:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    request.state.user = user
    return await call_next(request)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-me-before-production"), https_only=False)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return views.TemplateResponse(request, "login.html", {"error": ""})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = request.client.host if request.client else None
    s = db(); user = authenticate(s, username, password, client_ip)
    if not user:
        s.close()
        return views.TemplateResponse(request, "login.html", {"error": "Неверный логин или пароль."}, status_code=401)
    request.session["user_id"] = user.id
    s.close()
    return RedirectResponse("/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/", response_class=HTMLResponse)
def registry(request: Request, q: str = "", faculty: str = "", end_year: str = ""):
    s = db()
    contracts, faculties, counts, end_years = get_registry(s, q, faculty, end_year)
    return views.TemplateResponse(request, "registry.html", {"contracts": contracts, "faculties": faculties, "counts": counts, "q": q, "selected_faculty": faculty, "end_years": end_years, "selected_end_year": end_year})

@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, q: str = "", faculty: str = ""):
    s = db(); rows, faculties = application_registry(s, q, faculty)
    return views.TemplateResponse(request, "applications.html", {"applications": rows, "faculties": faculties, "q": q, "selected_faculty": faculty})

@app.get("/organizations/{org_id}/applications/new", response_class=HTMLResponse)
def new_application(request: Request, org_id: int):
    s = db(); org = s.get(Organization, org_id)
    if not org: raise HTTPException(404)
    return views.TemplateResponse(request, "application_form.html", {"org": org, "faculties": s.query(Faculty).order_by(Faculty.name).all()})

@app.post("/organizations/{org_id}/applications")
def add_application(request: Request, org_id: int, faculty: list[str] = Form(...), received_date: str = Form(...), number: str = Form(""), signed_date: str = Form("")):
    s = db(); application = create_application(s, org_id, faculty, received_date, number, signed_date, request.state.user.id, audit_actor=audit_actor(request))
    return RedirectResponse(f"/applications/{application.id}", status_code=303)

@app.get("/applications/{application_id}", response_class=HTMLResponse)
def application_card(request: Request, application_id: int):
    s = db(); application = s.get(Application, application_id)
    if not application: raise HTTPException(404)
    years = list(range(date.today().year, date.today().year + 10))
    return views.TemplateResponse(request, "application.html", {"application": application, "years": years})

@app.post("/applications/{application_id}")
def edit_application(request: Request, application_id: int, number: str = Form(""), signed_date: str = Form("")):
    s = db(); application = s.get(Application, application_id)
    if not application: raise HTTPException(404)
    update_application(s, application, number, signed_date, audit_actor=audit_actor(request))
    return RedirectResponse(f"/applications/{application_id}", status_code=303)

@app.post("/applications/{application_id}/status")
def set_application_status(request: Request, application_id: int, status: str = Form(...), comment: str = Form("")):
    s = db(); application = s.get(Application, application_id)
    if not application: raise HTTPException(404)
    try:
        change_application_status(s, application, status, request.state.user.role, comment, audit_actor=audit_actor(request))
    except StatusTransitionError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return {
        "status": application.status,
        "status_class": status_class(application.status),
        "transitions": allowed_status_transitions("application", application.status, request.state.user.role),
    }

@app.post("/applications/{application_id}/items")
async def add_application_item(request: Request, application_id: int, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); application = s.get(Application, application_id)
    if not application: raise HTTPException(404)
    save_application_item(s, application, specialty, qualification, await request.form(), audit_actor=audit_actor(request))
    return RedirectResponse(f"/applications/{application_id}", status_code=303)

@app.post("/application-items/{item_id}")
async def edit_application_item(request: Request, item_id: int, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); item = s.get(OrderItem, item_id)
    if not item or not item.order.application_id: raise HTTPException(404)
    application = s.get(Application, item.order.application_id)
    save_application_item(s, application, specialty, qualification, await request.form(), item, audit_actor=audit_actor(request))
    return RedirectResponse(f"/applications/{application.id}", status_code=303)

@app.post("/applications/{application_id}/scan")
async def add_application_scan(request: Request, application_id: int, file: UploadFile = File(...)):
    s = db(); application = s.get(Application, application_id)
    if not application: raise HTTPException(404)
    safe = Path(file.filename).name; stored = f"{uuid.uuid4()}-{safe}"
    target = Path("uploads") / stored
    with open(target, "wb") as out: shutil.copyfileobj(file.file, out)
    try:
        attach_application_scan(s, application, safe, stored, audit_actor=audit_actor(request))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return RedirectResponse(f"/applications/{application_id}", status_code=303)

@app.post("/import")
async def upload_import(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"): raise HTTPException(400, "Нужен файл Excel .xlsx")
    original_filename = Path(file.filename).name
    path = Path("uploads") / f"import-{uuid.uuid4()}.xlsx"
    with path.open("wb") as out: shutil.copyfileobj(file.file, out)
    s = db()
    try:
        import_xlsx(s, path, request.state.user.id, original_filename, audit_actor=audit_actor(request))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        s.close()
    return RedirectResponse("/", status_code=303)

@app.get("/organizations/new", response_class=HTMLResponse)
def new_org(request: Request): return views.TemplateResponse(request, "organization_form.html", {})

@app.post("/organizations/new")
def create_org(request: Request, name: str = Form(...), full_name: str = Form(""), address: str = Form(""), department: str = Form("")):
    s = db(); org = create_organization(s, name=name, full_name=full_name, address=address, department=department, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{org.id}", status_code=303)

@app.post("/organizations/{org_id}")
def edit_organization(request: Request, org_id: int, name: str = Form(...), full_name: str = Form(""), address: str = Form(""), department: str = Form(""), phone: str = Form("")):
    s = db(); org = s.get(Organization, org_id)
    if not org: raise HTTPException(404)
    update_organization(s, org, name=name, full_name=full_name, address=address, department=department, phone=phone, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{org.id}", status_code=303)

@app.get("/organizations/{org_id}", response_class=HTMLResponse)
def organization(request: Request, org_id: int):
    s = db(); org = s.get(Organization, org_id)
    if not org: raise HTTPException(404)
    years = sorted({year for c in org.contracts for i in c.items for year in json.loads(i.demand_json).keys()})
    return views.TemplateResponse(request, "organization.html", {"org": org, "years": years, "all_faculties": s.query(Faculty).order_by(Faculty.name).all()})

@app.post("/organizations/{org_id}/contract")
def add_contract(request: Request, org_id: int, faculty: list[str] = Form(...), number: str = Form(""), end_date: str = Form("")):
    s = db(); create_contract(s, org_id, faculty, number, end_date, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{org_id}", status_code=303)

@app.post("/contracts/{contract_id}")
def edit_contract(request: Request, contract_id: int, number: str = Form(...), start_date: str = Form(...), end_date: str = Form("")):
    s = db(); contract = s.get(Contract, contract_id)
    if not contract: raise HTTPException(404)
    update_contract(s, contract, number, start_date, end_date, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{contract.organization_id}", status_code=303)

@app.post("/contracts/{contract_id}/status")
def set_contract_status(request: Request, contract_id: int, status: str = Form(...), comment: str = Form("")):
    s = db(); contract = s.get(Contract, contract_id)
    if not contract: raise HTTPException(404)
    try:
        change_contract_status(s, contract, status, request.state.user.role, comment, audit_actor=audit_actor(request))
    except StatusTransitionError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return {
        "status": contract.status,
        "status_class": status_class(contract.status),
        "transitions": allowed_status_transitions("contract", contract.status, request.state.user.role),
    }

@app.post("/contracts/{contract_id}/additional-agreements")
def add_additional_agreement(request: Request, contract_id: int, number: str = Form(...), agreement_date: str = Form(...)):
    s = db(); contract = s.get(Contract, contract_id)
    if not contract: raise HTTPException(404)
    agreement = register_additional_agreement(s, contract, number, date.fromisoformat(agreement_date), request.state.user.id, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{contract.organization_id}", status_code=303)

@app.post("/additional-agreements/{agreement_id}/status")
def set_agreement_status(request: Request, agreement_id: int, status: str = Form(...), comment: str = Form("")):
    s = db(); agreement = s.get(AdditionalAgreement, agreement_id)
    if not agreement: raise HTTPException(404)
    try:
        change_agreement_status(s, agreement, status, request.state.user.role, comment, audit_actor=audit_actor(request))
    except StatusTransitionError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return {
        "status": agreement.status,
        "status_class": status_class(agreement.status),
        "transitions": allowed_status_transitions("additional_agreement", agreement.status, request.state.user.role),
    }

@app.get("/additional-agreements/{agreement_id}/comparison", response_class=HTMLResponse)
def agreement_comparison(request: Request, agreement_id: int):
    s = db(); agreement = s.get(AdditionalAgreement, agreement_id)
    if not agreement: raise HTTPException(404)
    rows, years = compare_agreement_order(s, agreement)
    return views.TemplateResponse(request, "agreement_comparison.html", {"agreement": agreement, "rows": rows, "years": years})

@app.post("/contracts/{contract_id}/items")
async def add_item(contract_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    form = await request.form()
    save_item(s, contract_id, specialty, qualification, form, user_id=request.state.user.id, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.post("/items/{item_id}")
async def edit_item(item_id: int, request: Request, specialty: str = Form(...), qualification: str = Form("")):
    s = db(); item = s.get(OrderItem, item_id)
    if not item: raise HTTPException(404)
    form = await request.form()
    save_item(s, item.contract_id, specialty, qualification, form, item, request.state.user.id, audit_actor=audit_actor(request))
    return RedirectResponse(f"/organizations/{item.contract.organization_id}", status_code=303)

@app.post("/items/{item_id}/delete")
def remove_item(request: Request, item_id: int):
    s = db(); item = s.get(OrderItem, item_id)
    if not item: raise HTTPException(404)
    destination = delete_item(s, item, audit_actor=audit_actor(request))
    if destination["application_id"]:
        return RedirectResponse(f"/applications/{destination['application_id']}", status_code=303)
    return RedirectResponse(f"/organizations/{destination['organization_id']}", status_code=303)

@app.post("/contracts/{contract_id}/scan")
async def add_scan(request: Request, contract_id: int, file: UploadFile = File(...)):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    safe = Path(file.filename).name; stored = f"{uuid.uuid4()}-{safe}"
    target = Path("uploads") / stored
    with open(target, "wb") as out: shutil.copyfileobj(file.file, out)
    try:
        attach_scan(s, c, safe, stored, audit_actor=audit_actor(request))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return RedirectResponse(f"/organizations/{c.organization_id}", status_code=303)

@app.get("/contracts/{contract_id}/agreement")
def agreement(contract_id: int):
    s = db(); c = s.get(Contract, contract_id)
    if not c: raise HTTPException(404)
    target = Path("uploads") / f"Дополнительное_соглашение_{contract_id}.docx"; render_agreement(c, target)
    return FileResponse(target, filename=target.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
