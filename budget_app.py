import streamlit as st
import pandas as pd
import bcrypt
import os
from datetime import datetime
from io import BytesIO

# ---------- 0. CONFIGURE PERSISTENCE ----------
DATA_FILE = "data.csv"

def load_data():
    """If data.csv exists, load it; otherwise return an empty DataFrame."""
    if os.path.exists(DATA_FILE):
        df = pd.read_csv(DATA_FILE, parse_dates=["Date"])
        return df
    else:
        # Same columns you’ve been using
        cols = [
            "Date", "Vendor", "Description", "Location", "Recovery Type",
            "Charged Amount", "Reimbursed Amount", "Invoice #", "CHQ REQ #", "Out of Pocket?"
        ]
        return pd.DataFrame(columns=cols)

def save_data(df: pd.DataFrame):
    """Write the DataFrame out to data.csv (overwriting)."""
    # Make sure Date is saved in YYYY-MM-DD format
    df_to_save = df.copy()
    df_to_save["Date"] = df_to_save["Date"].dt.strftime("%Y-%m-%d")
    df_to_save.to_csv(DATA_FILE, index=False)

# ---------- 1. LOGIN & RATE LIMITING ----------
# Pull bcrypt hashes from Streamlit secrets (as before):
USERS = {
    "Chad": st.secrets["bcrypt_hashes"]["Chad"].encode()
}
MAX_LOGIN_ATTEMPTS = 5

def verify_password(username: str, password: str) -> bool:
    hashed = USERS.get(username)
    if hashed is None:
        return False
    return bcrypt.checkpw(password.encode(), hashed)

st.set_page_config(page_title="Budget Tracker", page_icon="💰", layout="wide")
st.title("💰 Department Budget Tracker")

# Initialize login flags
if "logged" not in st.session_state:
    st.session_state.logged = False
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0

# Show login form if not authenticated
if not st.session_state.logged:
    st.markdown("## 🔒 Please log in to continue")
    if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
        st.error("🚫 Too many failed login attempts. Restart the app to retry.")
        st.stop()

    with st.form("login_form", clear_on_submit=False):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log In")
        if submitted:
            if verify_password(u, p):
                st.session_state.logged = True
                st.success(f"✅ Logged in as '{u}'.")
            else:
                st.session_state.login_attempts += 1
                left = MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts
                st.error(f"❌ Wrong credentials. Attempts left: {left}")
    st.stop()

# ---------- 2. LOAD OR INITIALIZE THE DATAFRAME ----------
# We store all rows in data.csv on disk for persistence.
if "df" not in st.session_state:
    df_initial = load_data()
    # Ensure “Date” column is datetime type
    if not df_initial.empty:
        df_initial["Date"] = pd.to_datetime(df_initial["Date"])
    st.session_state.df = df_initial

# ---------- 3. TOTAL BUDGET INPUT ----------
st.markdown("### Budget Settings")
budget_total = st.number_input(
    "Total budget ($)", value=10000.0, step=100.0, format="%.2f"
)
st.markdown("---\n")

# ---------- 4. ADD ENTRY FORM ----------
st.markdown("### ➕ Add a New Expense")
with st.form("add_row", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
        d   = st.date_input("Date", value=datetime.today())
        ven = st.text_input("Vendor")
        des = st.text_input("Description")
        loc = st.text_input("Location")
        rty = st.text_input("Recovery Type")
    with c2:
        amt   = st.number_input("Charged Amount ($)", min_value=0.0, format="%.2f")
        reimb = (amt / 1.13) * 1.0341
        st.write(f"Reimbursed (auto): **${reimb:,.2f}**")
        inv = st.text_input("Invoice #")
        chq = st.text_input("CHQ REQ #")
        oop = st.checkbox("❌ Out of Pocket?")
    if st.form_submit_button("Add / Update"):
        new_row = pd.DataFrame([{
            "Date": pd.to_datetime(d),
            "Vendor": ven,
            "Description": des,
            "Location": loc,
            "Recovery Type": rty,
            "Charged Amount": amt,
            "Reimbursed Amount": reimb,
            "Invoice #": inv,
            "CHQ REQ #": chq,
            "Out of Pocket?": oop,
        }])
        st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
        # Immediately save to CSV
        save_data(st.session_state.df)
        st.success("✅ Row added and saved.")

st.markdown("---\n")

# ---------- 5. DELETE ENTRY (and re-save) ----------
with st.expander("🗑 Delete an entry"):
    df_live = st.session_state.df
    if df_live.empty:
        st.info("No rows to delete.")
    else:
        choices = {
            f"{idx} | {row['Vendor']} | {row['Date'].date()}": idx
            for idx, row in df_live.iterrows()
        }
        option = st.selectbox("Pick a row to delete", list(choices.keys()))
        if st.button("Delete selected row"):
            drop_idx = choices[option]
            df_live.drop(index=drop_idx, inplace=True)
            df_live.reset_index(drop=True, inplace=True)
            # Save after deletion
            save_data(df_live)
            st.success("✅ Row deleted and saved.")
st.markdown("---\n")

# ---------- 6. REFRESH COPY AFTER ANY DELETES OR ADDS ----------
df = st.session_state.df.copy()

# ---------- 7. SUMMARY CALCULATIONS ----------
spent_oop = df[df["Out of Pocket?"] == True]["Charged Amount"].sum()
spent_diff = (
    df[df["Out of Pocket?"] == False]
      .eval("`Charged Amount` - `Reimbursed Amount`")
      .sum()
)
spent_total = spent_oop + spent_diff
remaining    = budget_total - spent_total

st.markdown("### 📊 Budget Summary")
colA, colB, colC = st.columns(3)
colA.metric("Total budget",    f"${budget_total:,.2f}")
colB.metric("Spent so far",    f"${spent_total:,.2f}")
colC.metric("Remaining budget", f"${remaining:,.2f}")
st.markdown("---\n")

# ---------- 8. STYLED TABLE ----------
def style_row(r):
    return ["color: red" if r["Out of Pocket?"] else "color: white"] * len(r)

st.markdown("### 📋 Current Expenses")
st.dataframe(
    df.style.apply(style_row, axis=1),
    use_container_width=True,
    height=420
)

# ---------- 9. DOWNLOAD BUTTONS ----------
def to_xlsx(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Expenses")
    return buffer.getvalue()

reimb_only = df[df["Out of Pocket?"] == False]
oop_only   = df[df["Out of Pocket?"] == True]

d1, d2 = st.columns(2)
d1.download_button(
    "⬇️ Reimbursed-only sheet",
    data=to_xlsx(reimb_only),
    file_name="Reimbursed_Expenses.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
d2.download_button(
    "⬇️ Out-of-Pocket-only sheet",
    data=to_xlsx(oop_only),
    file_name="OutOfPocket_Expenses.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
