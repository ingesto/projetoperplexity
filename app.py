# app.py - Streamlit Dashboard completo

import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder
import json
import base64
import io
from fpdf import FPDF
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os

# --- Configuração de Conexão com PostgreSQL ---
def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT", 5432),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB")
    )

# --- Autenticação básica multiusuário ---
USERS_JSON = os.getenv("USERS_JSON", '{"admin":"admin_pass","analyst":"analyst_pass","reader":"reader_pass"}')
users = json.loads(USERS_JSON)

def login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if not st.session_state.logged_in:
        st.title("Login")
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            if username in users and users[username] == password:
                st.session_state.logged_in = True
                st.session_state.user = username
                st.experimental_rerun()
            else:
                st.error("Usuário ou senha incorretos")
        st.stop()

def check_role():
    role_map = {"admin":"admin", "analyst":"analyst", "reader":"reader"}
    return role_map.get(st.session_state.user, "reader")

# --- Carregar dados CSV para PostgreSQL (executar uma vez ou via botão) ---
def load_csv_to_postgres(file):
    df = pd.read_csv(file)
    conn = get_connection()
    cur = conn.cursor()
    # Criar tabela exemplo
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dados (
            id SERIAL PRIMARY KEY,
            coluna1 TEXT,
            coluna2 TEXT,
            valor NUMERIC
        )
    """)
    conn.commit()

    # Limpar tabela antes de carregar
    cur.execute("DELETE FROM dados")
    conn.commit()
    # Inserir dados
    for _, row in df.iterrows():
        cur.execute("INSERT INTO dados (coluna1, coluna2, valor) VALUES (%s,%s,%s)", (row[0], row[1], row[2]))
    conn.commit()
    cur.close()
    conn.close()

# --- Ler dados do PostgreSQL ---
def get_data():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM dados")
    data = cur.fetchall()
    cur.close()
    conn.close()
    return pd.DataFrame(data)

# --- Exportar para Excel ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    processed_data = output.getvalue()
    return processed_data

# --- Exportar para PDF ---
def to_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    line_height = pdf.font_size * 2
    col_width = pdf.epw / len(df.columns)

    # Header
    for col in df.columns:
        pdf.cell(col_width, line_height, col, border=1)
    pdf.ln(line_height)
    # Rows
    for _, row in df.iterrows():
        for item in row:
            pdf.cell(col_width, line_height, str(item), border=1)
        pdf.ln(line_height)

    return pdf.output(dest='S').encode('latin1')

# --- Enviar email com anexo ---
def send_email(to_email, subject, body, attachment_bytes, filename):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, 'plain'))
    part = MIMEApplication(attachment_bytes, Name=filename)
    part['Content-Disposition'] = f'attachment; filename="{filename}"'
    msg.attach(part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

# --- Main app ---
def main():
    st.set_page_config(
        page_title="Dashboard Customizado",
        layout="wide",
        initial_sidebar_state="expanded",
        page_icon="📊",
        menu_items=None
    )

    # Aplicar tema (via config / variáveis enter streamlit config)
    st.sidebar.title("Menu")
    st.sidebar.markdown("### Navegação")

    login()
    role = check_role()

    if role == "reader":
        st.sidebar.info("Modo leitura. Permissões restritas.")
    elif role == "analyst":
        st.sidebar.info("Modo analista. Pode filtrar e exportar.")
    else:
        st.sidebar.info("Modo administrador. Controle total.")

    # Upload CSV para carregamento inicial (admin)
    if role == "admin":
        file = st.sidebar.file_uploader("Upload CSV para importar dados", type=["csv"])
        if file:
            load_csv_to_postgres(file)
            st.success("Dados importados com sucesso!")

    data = get_data()
    st.title("Dashboard Interativo")

    # Filtros dinâmicos
    col1, col2 = st.columns(2)
    with col1:
        filtro_coluna1 = st.selectbox("Filtrar Coluna 1", options=["Todos"] + list(data["coluna1"].unique()))
    with col2:
        filtro_coluna2 = st.selectbox("Filtrar Coluna 2", options=["Todos"] + list(data["coluna2"].unique()))

    df_filtrado = data.copy()
    if filtro_coluna1 != "Todos":
        df_filtrado = df_filtrado[df_filtrado["coluna1"] == filtro_coluna1]
    if filtro_coluna2 != "Todos":
        df_filtrado = df_filtrado[df_filtrado["coluna2"] == filtro_coluna2]

    # Exibir tabela com AgGrid
    gb = GridOptionsBuilder.from_dataframe(df_filtrado)
    gb.configure_default_column(editable=True, filter=True, sortable=True)
    grid_options = gb.build()
    AgGrid(df_filtrado, gridOptions=grid_options, height=300, fit_columns_on_grid_load=True)

    # Gráfico
    fig = px.bar(df_filtrado, x="coluna1", y="valor", color="coluna2", barmode="group", title="Gráfico Interativo")
    st.plotly_chart(fig, use_container_width=True)

    # Exportar dados
    st.markdown("### Exportar dados")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        excel_data = to_excel(df_filtrado)
        st.download_button(label="Exportar Excel", data=excel_data, file_name="dados.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col_exp2:
        pdf_data = to_pdf(df_filtrado)
        st.download_button(label="Exportar PDF", data=pdf_data, file_name="dados.pdf", mime="application/pdf")

if __name__ == "__main__":
    main()
