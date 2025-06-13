# ── 0. Page config MUST come before any other st.* call ────────────────────
import streamlit as st
st.set_page_config(
    page_title="EMCO Budget Tracker",
    page_icon="💰",
    layout="wide",
)

# ── 1. Standard imports ───────────────────────────────────────────────────
import pandas as pd
import numpy as np
import bcrypt
from datetime import datetime
from io import BytesIO
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# ── 2. Database connection ─────────────────────────────────────────────────
ENGINE = create_engine(
    st.secrets["supabase"]["pooler"],  # Session-Pooler URL
    pool_pre_ping=True,
)

# ── 3. Column definitions ──────────────────────────────────────────────────
RAW = [
    "id", "date", "vendor", "description", "location", "recovery_type",
    "charged_amount", "invoice", "chq_req", "out_of_pocket",
]
PRETTY = {
    "date": "Date", "vendor": "Vendor", "description": "Description",
    "location": "Location", "recovery_type": "Recovery Type",
    "charged_amount": "Charged Amount", "reimbursed_amount": "Reimbursed Amount",
    "invoice": "Invoice #", "chq_req": "CHQ REQ #",
    "out_of_pocket": "Out of Pocket?",
}

# ── 4. Helpers ─────────────────────────────────────────────────────────────
def _clean_cols(cols: pd.Index) -> pd.Index:
    return (
        cols.str.replace(r"[\u200B-\u200D\uFEFF]", "", regex=True)
            .str.strip().str.lower().str.replace(" ", "_")
    )

def load_data() -> pd.DataFrame:
    """Load & normalise the full expenses table, then compute reimbursements."""
    try:
        df = pd.read_sql(
            "SELECT id, date, vendor, description, location, recovery_type,"
            "charged_amount, invoice, chq_req, out_of_pocket "
            "FROM expenses ORDER BY id",
            ENGINE, parse_dates=["date"]
        )
    except SQLAlchemyError as e:
        st.error(f"🚫 Database error: {e}")
        return pd.DataFrame(columns=RAW + ["reimbursed_amount"])

    df.columns = _clean_cols(df.columns)
    # Ensure every RAW column exists
    for col in RAW:
        if col not in df.columns:
            df[col] = False if col == "out_of_pocket" else pd.NA

    # dtype coercion
    df["out_of_pocket"]  = df["out_of_pocket"].fillna(False).astype(bool)
    df["charged_amount"] = pd.to_numeric(df["charged_amount"], errors="coerce").fillna(0.0)

    # **Recompute reimbursed_amount on-the-fly**:
    df["reimbursed_amount"] = np.where(
        df["out_of_pocket"],
        0.0,
        df["charged_amount"]
    )

    return df[RAW + ["reimbursed_amount"]]

def save_row(data: dict) -> None:
    sql = text("""
        INSERT INTO expenses
        (date, vendor, description, location, recovery_type,
         charged_amount, reimbursed_amount, invoice, chq_req, out_of_pocket)
        VALUES
        (:date, :vendor, :description, :location, :recovery_type,
         :charged_amount, :reimbursed_amount, :invoice, :chq_req, :out_of_pocket)
    """)
    with ENGINE.begin() as conn:
        conn.execute(sql, data)

def delete_row(rid: int) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM expenses WHERE id = :rid"), {"rid": rid})

def prettify(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.rename(columns=PRETTY, errors="ignore")
          .drop(columns="id", errors="ignore")
    )

def to_xlsx(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Expenses")
    return buf.getvalue()

# ── 5. Simple login ────────────────────────────────────────────────────────
USERS = {"Chad": st.secrets["bcrypt_hashes"]["Chad"].encode()}
def authenticate(user: str, pwd: str) -> bool:
    h = USERS.get(user)
    return bool(h and bcrypt.checkpw(pwd.encode(), h))

if "logged" not in st.session_state:
    st.session_state.logged = False
if "tries" not in st.session_state:
    st.session_state.tries = 0

if not st.session_state.logged:
    if st.session_state.tries >= 5:
        st.error("Too many failed logins. Restart the app."); st.stop()
    with st.form("login", clear_on_submit=True):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            if authenticate(u, p):
                st.session_state.logged = True
            else:
                st.session_state.tries += 1
                st.error(f"Wrong credentials. {5 - st.session_state.tries} tries left.")
    st.stop()

# ── 6. Title & load fresh data ─────────────────────────────────────────────
st.title("EMCO Budget Tracker")
df = load_data()

# ── 7. Budget header ──────────────────────────────────────────────────────
BUDGET = 400_000.0
st.markdown(f"### Budget: **${BUDGET:,.2f}** *(fixed)*")
st.markdown("---")

# ── 8. Add / Update expense ───────────────────────────────────────────────
with st.form("add", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        d   = st.date_input("Date", datetime.today())
        ven = st.text_input("Vendor")
        des = st.text_input("Description")
        loc = st.text_input("Location")
        rty = st.text_input("Recovery Type")
    with c2:
        amt   = st.number_input("Charged Amount ($)", min_value=0.0, format="%.2f")
        oop   = st.checkbox("❌ Out of Pocket?")
        reimb = 0.0 if oop else amt
        st.write(f"Reimbursed (auto): **${reimb:,.2f}**")
        inv = st.text_input("Invoice #")
        chq = st.text_input("CHQ REQ #")
    if st.form_submit_button("Save"):
        save_row({
            "date": pd.to_datetime(d),
            "vendor": ven,
            "description": des,
            "location": loc,
            "recovery_type": rty,
            "charged_amount": amt,
            "reimbursed_amount": reimb,
            "invoice": inv,
            "chq_req": chq,
            "out_of_pocket": oop,
        })
        st.experimental_rerun()

st.markdown("---")

# ── 9. Delete entry ────────────────────────────────────────────────────────
with st.expander("🗑 Delete an entry"):
    if df.empty:
        st.info("No rows in database.")
    else:
        choices = {
            f"{r.vendor} | {r.date.date()} | ID={r.id}": r.id
            for r in df.itertuples()
        }
        sel = st.selectbox("Pick a row", list(choices.keys()))
        if st.button("Delete"):
            delete_row(choices[sel])
            st.experimental_rerun()

st.markdown("---")

# ── 10. Budget summary ─────────────────────────────────────────────────────
mask       = df["out_of_pocket"]
spent_oop  = df.loc[mask,  "charged_amount"].sum()
spent_diff = (df.loc[~mask, "charged_amount"] -
              df.loc[~mask, "reimbursed_amount"]).sum()
spent_tot  = spent_oop + spent_diff
remaining  = BUDGET - spent_tot

c1, c2, c3 = st.columns(3)
c1.metric("Total Budget", f"${BUDGET:,.2f}")
c2.metric("Amount Spent", f"${spent_tot:,.2f}")
c3.metric("Remaining",    f"${remaining:,.2f}")
st.markdown("---")

# ── 11. Table & downloads ─────────────────────────────────────────────────
disp = prettify(df)
st.dataframe(
    disp.style.apply(lambda r: ["color:red" if r["Out of Pocket?"] else "" ]*len(r), axis=1),
    use_container_width=True, height=420
)

colA, colB = st.columns(2)
colA.download_button(
    "⬇️ Reimbursed-only",
    to_xlsx(prettify(df.loc[~mask])),
    "Reimbursed_Expenses.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
colB.download_button(
    "⬇️ Out-of-Pocket-only",
    to_xlsx(prettify(df.loc[mask])),
    "OutOfPocket_Expenses.xlsx",
    mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet"
)
