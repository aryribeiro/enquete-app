import streamlit as st
import pandas as pd
import html as html_module
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from streamlit.components.v1 import html

# --- Constantes ---
DB_NAME = "enquete_app_vfinal_cookie.db"
MIN_OPTIONS = 2
MAX_OPTIONS = 10
DEFAULT_NUM_OPTIONS_ON_NEW = 2
HISTORICO_LIMIT = 5
UTC_TZ = ZoneInfo("UTC")
BR_TZ = ZoneInfo("America/Sao_Paulo")
SALT_SECRET = os.environ.get("PASSWORD_SALT", "enquete-app-default-salt-2024")

# --- Page Config ---
st.set_page_config(
    page_title="Enquete App | Sua enquete em tempo real",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- CSS (estático, injetado uma vez via constante) ---
_CSS = """
<style>
    .main > div {
        padding-top: 1rem;
    }
    .stApp > header {
        background-color: transparent;
    }
    footer {
        visibility: hidden !important;
    }
    .stButton>button { width: 100%; }
    .sidebar-history-link a {
        font-size: 0.9em;
        text-decoration: none;
        display: block;
        padding: 4px 0px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .sidebar-history-link a:hover {
        text-decoration: underline;
    }
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)


# --- Utilitários ---
def hash_password(password):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        SALT_SECRET.encode(),
        iterations=100_000,
    ).hex()


def format_timestamp_br(timestamp_str):
    if not timestamp_str:
        return "Data não disponível"
    try:
        if timestamp_str.endswith("Z"):
            utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            naive_dt = datetime.fromisoformat(timestamp_str)
            utc_dt = naive_dt.replace(tzinfo=UTC_TZ) if naive_dt.tzinfo is None else naive_dt.astimezone(UTC_TZ)
        return utc_dt.astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        try:
            naive_dt = datetime.strptime(timestamp_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            return naive_dt.replace(tzinfo=UTC_TZ).astimezone(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return timestamp_str.split(".")[0]


def format_timestamp_br_short(timestamp_str):
    if not timestamp_str:
        return "Data inválida"
    try:
        if timestamp_str.endswith("Z"):
            utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            naive_dt = datetime.fromisoformat(timestamp_str)
            utc_dt = naive_dt.replace(tzinfo=UTC_TZ) if naive_dt.tzinfo is None else naive_dt.astimezone(UTC_TZ)
        return utc_dt.astimezone(BR_TZ).strftime("%d/%m %H:%M")
    except ValueError:
        try:
            naive_dt = datetime.strptime(timestamp_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            return naive_dt.replace(tzinfo=UTC_TZ).astimezone(BR_TZ).strftime("%d/%m %H:%M")
        except ValueError:
            return timestamp_str.split(" ")[0]


def _safe_db_execute(fn, default=None):
    try:
        return fn()
    except sqlite3.OperationalError:
        time.sleep(0.1)
        try:
            return fn()
        except sqlite3.OperationalError as e:
            st.error(f"Erro de acesso ao banco de dados: {e}")
            return default


# --- Banco de Dados ---
@st.cache_resource
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_resource
def _init_db_once():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracao (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)
    admin_password_hash = hash_password("admin123")
    cursor.execute(
        "INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)",
        ("senha_professor", admin_password_hash),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)",
        ("enquete_ativa", "0"),
    )
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_definicao (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        pergunta TEXT,
        opcoes_json TEXT
    )
    """)
    default_opcoes_json = json.dumps([""] * DEFAULT_NUM_OPTIONS_ON_NEW)
    cursor.execute(
        "INSERT OR IGNORE INTO enquete_ativa_definicao (id, pergunta, opcoes_json) VALUES (1, ?, ?)",
        ("", default_opcoes_json),
    )
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_votos (
        opcao_indice INTEGER PRIMARY KEY,
        contagem INTEGER DEFAULT 0
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_cookie_votantes (
        user_voting_id TEXT PRIMARY KEY,
        vote_timestamp TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historico_enquetes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'NOW')),
        pergunta TEXT NOT NULL,
        opcoes_json TEXT NOT NULL,
        votos_json TEXT NOT NULL,
        total_votos INTEGER DEFAULT 0
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historico_timestamp ON historico_enquetes (timestamp DESC);")
    conn.commit()
    return True


def db_adicionar_ao_historico(pergunta, opcoes_lista, votos_lista, total_votos_final):
    if not pergunta or not opcoes_lista:
        return
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO historico_enquetes (pergunta, opcoes_json, votos_json, total_votos) VALUES (?, ?, ?, ?)",
            (pergunta, json.dumps(opcoes_lista), json.dumps(votos_lista), total_votos_final),
        )
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao salvar enquete no histórico: {e}")
        return
    _db_manter_limite_historico()


def _db_manter_limite_historico(limite=HISTORICO_LIMIT):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as count FROM historico_enquetes").fetchone()
        if row and row["count"] > limite:
            num_to_delete = row["count"] - limite
            conn.execute(
                """DELETE FROM historico_enquetes WHERE id IN (
                    SELECT id FROM historico_enquetes ORDER BY timestamp ASC, id ASC LIMIT ?
                )""",
                (num_to_delete,),
            )
            conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao manter limite do histórico: {e}")


def db_carregar_historico(limite=HISTORICO_LIMIT):
    def _query():
        conn = get_db_connection()
        return conn.execute(
            "SELECT id, pergunta, timestamp FROM historico_enquetes ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    result = _safe_db_execute(_query, default=[])
    return result if result is not None else []


def db_carregar_enquete_historico_por_id(id_historico):
    def _query():
        conn = get_db_connection()
        row = conn.execute(
            "SELECT pergunta, opcoes_json, votos_json, total_votos, timestamp FROM historico_enquetes WHERE id = ?",
            (id_historico,),
        ).fetchone()
        if row:
            return {
                "pergunta": row["pergunta"],
                "opcoes": json.loads(row["opcoes_json"]),
                "votos": json.loads(row["votos_json"]),
                "total_votos": row["total_votos"],
                "timestamp": row["timestamp"],
            }
        return None
    return _safe_db_execute(_query, default=None)


def db_carregar_config_valor(chave, default=None):
    def _query():
        conn = get_db_connection()
        row = conn.execute("SELECT valor FROM configuracao WHERE chave = ?", (chave,)).fetchone()
        if row:
            if chave == "enquete_ativa":
                return row["valor"] == "1"
            return row["valor"]
        return default
    result = _safe_db_execute(_query, default=default)
    return result if result is not None else default


def db_salvar_config_valor(chave, valor):
    conn = get_db_connection()
    valor_db = "1" if (chave == "enquete_ativa" and valor) else ("0" if chave == "enquete_ativa" else valor)
    try:
        conn.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", (chave, valor_db))
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao salvar configuração: {e}")


def db_carregar_dados_enquete():
    def _query():
        conn = get_db_connection()
        row = conn.execute("SELECT pergunta, opcoes_json FROM enquete_ativa_definicao WHERE id = 1").fetchone()
        if row and row["opcoes_json"]:
            try:
                return {"pergunta": row["pergunta"], "opcoes": json.loads(row["opcoes_json"])}
            except json.JSONDecodeError:
                pass
        return {"pergunta": "", "opcoes": [""] * DEFAULT_NUM_OPTIONS_ON_NEW}
    result = _safe_db_execute(_query, default={"pergunta": "", "opcoes": [""] * DEFAULT_NUM_OPTIONS_ON_NEW})
    return result


def db_salvar_dados_enquete(pergunta, opcoes_lista):
    conn = get_db_connection()
    try:
        conn.execute(
            "REPLACE INTO enquete_ativa_definicao (id, pergunta, opcoes_json) VALUES (1, ?, ?)",
            (pergunta, json.dumps(opcoes_lista)),
        )
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao salvar enquete: {e}")


def db_limpar_votos_e_cookies(num_opcoes_enquete_atual):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM enquete_ativa_votos")
        conn.execute("DELETE FROM enquete_ativa_cookie_votantes")
        num_opcoes_valido = max(MIN_OPTIONS, min(num_opcoes_enquete_atual, MAX_OPTIONS))
        for i in range(num_opcoes_valido):
            conn.execute("INSERT INTO enquete_ativa_votos (opcao_indice, contagem) VALUES (?, 0)", (i,))
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao limpar votos: {e}")


def db_carregar_resultados(num_opcoes_enquete_atual):
    def _query():
        conn = get_db_connection()
        votos_rows = conn.execute(
            "SELECT opcao_indice, contagem FROM enquete_ativa_votos ORDER BY opcao_indice ASC"
        ).fetchall()
        total_row = conn.execute("SELECT SUM(contagem) as total_votos FROM enquete_ativa_votos").fetchone()
        total_votos = total_row["total_votos"] if total_row and total_row["total_votos"] is not None else 0
        votos_lista = [0] * num_opcoes_enquete_atual
        for row in votos_rows:
            if 0 <= row["opcao_indice"] < num_opcoes_enquete_atual:
                votos_lista[row["opcao_indice"]] = row["contagem"]
        return {"votos": votos_lista, "total_votos": total_votos}
    result = _safe_db_execute(_query, default={"votos": [0] * num_opcoes_enquete_atual, "total_votos": 0})
    return result


def db_registrar_voto(opcao_indice, user_voting_id):
    conn = get_db_connection()
    try:
        vote_ts = datetime.now(UTC_TZ).isoformat()
        conn.execute(
            "INSERT INTO enquete_ativa_cookie_votantes (user_voting_id, vote_timestamp) VALUES (?, ?)",
            (user_voting_id, vote_ts),
        )
        cursor = conn.execute(
            "UPDATE enquete_ativa_votos SET contagem = contagem + 1 WHERE opcao_indice = ?",
            (opcao_indice,),
        )
        if cursor.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    except sqlite3.Error:
        conn.rollback()
        return False


def db_verificar_se_cookie_votou(user_voting_id):
    if not user_voting_id:
        return False

    def _query():
        conn = get_db_connection()
        row = conn.execute(
            "SELECT 1 FROM enquete_ativa_cookie_votantes WHERE user_voting_id = ?",
            (user_voting_id,),
        ).fetchone()
        return row is not None
    result = _safe_db_execute(_query, default=False)
    return bool(result)


# --- Session State ---
def initialize_session_state():
    defaults = {
        "modo": "aluno",
        "voto_registrado_nesta_sessao": False,
        "pagina_professor": "painel",
        "num_opcoes_edicao": DEFAULT_NUM_OPTIONS_ON_NEW,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# --- Telas ---
def mostrar_tela_login():
    st.title("🔐 Login do Professor")
    senha_digitada = st.text_input("Senha", type="password", key="login_senha_vfinal")
    if st.button("Entrar", key="login_entrar_vfinal"):
        senha_hash_db = db_carregar_config_valor("senha_professor")
        if senha_hash_db and hmac.compare_digest(hash_password(senha_digitada), senha_hash_db):
            st.session_state.modo = "professor"
            st.session_state.pagina_professor = "painel"
            st.success("Login realizado com sucesso!")
            st.rerun()
        else:
            st.error("Senha incorreta!")


def mostrar_painel_professor():
    st.title("🖥️ Painel do Professor")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🔐 Alterar Senha", key="painel_btn_alt_senha", use_container_width=True):
            st.session_state.pagina_professor = "alterar_senha"
            st.rerun()
            return
    with col_nav2:
        if st.button("🚪 Logout", key="painel_btn_logout", use_container_width=True):
            st.session_state.modo = "login_professor"
            st.session_state.pagina_professor = "painel"
            st.session_state.voto_registrado_nesta_sessao = False
            st.rerun()
            return
    st.divider()

    enquete_ativa_db = db_carregar_config_valor("enquete_ativa", False)
    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_salvas = dados_enquete_db.get("opcoes", [])
    num_opcoes_atuais = len(opcoes_salvas) if opcoes_salvas else st.session_state.num_opcoes_edicao
    if "num_opcoes_edicao_loaded" not in st.session_state or st.session_state.num_opcoes_edicao_loaded != num_opcoes_atuais:
        st.session_state.num_opcoes_edicao = max(MIN_OPTIONS, min(num_opcoes_atuais, MAX_OPTIONS))
        st.session_state.num_opcoes_edicao_loaded = num_opcoes_atuais

    num_opcoes_widget_key = "prof_num_opcoes_selector_v2"
    if num_opcoes_widget_key not in st.session_state:
        st.session_state[num_opcoes_widget_key] = st.session_state.num_opcoes_edicao

    def update_num_opcoes_edicao():
        st.session_state.num_opcoes_edicao = st.session_state[num_opcoes_widget_key]
        st.session_state.num_opcoes_edicao_loaded = st.session_state[num_opcoes_widget_key]

    num_opcoes_widget = st.number_input(
        "Número de Opções de Resposta:",
        min_value=MIN_OPTIONS,
        max_value=MAX_OPTIONS,
        key=num_opcoes_widget_key,
        on_change=update_num_opcoes_edicao,
    )
    if st.session_state.num_opcoes_edicao != num_opcoes_widget:
        st.session_state.num_opcoes_edicao = num_opcoes_widget
        st.session_state.num_opcoes_edicao_loaded = num_opcoes_widget

    st.subheader("Gerenciar Enquete")
    with st.form("painel_enquete_form_db_vfinal"):
        pergunta_form = st.text_input(
            "Pergunta da Enquete",
            value=dados_enquete_db.get("pergunta", ""),
            key="painel_pergunta_db_vfinal",
        )
        st.write(f"Opções de Resposta ({st.session_state.num_opcoes_edicao} opções):")
        opcoes_form_inputs = [""] * st.session_state.num_opcoes_edicao
        for i in range(st.session_state.num_opcoes_edicao):
            val_opt = opcoes_salvas[i] if i < len(opcoes_salvas) else ""
            opcoes_form_inputs[i] = st.text_input(f"Opção {i+1}", value=val_opt, key=f"painel_opt_db_vfinal_{i}")
        submit_save_enquete = st.form_submit_button("Salvar e Ativar Enquete")

    if submit_save_enquete:
        dados_enquete_anterior = db_carregar_dados_enquete()
        enquete_estava_ativa = db_carregar_config_valor("enquete_ativa", False)
        if enquete_estava_ativa and dados_enquete_anterior.get("pergunta", "").strip():
            num_opcoes_anterior = len(dados_enquete_anterior.get("opcoes", []))
            if num_opcoes_anterior >= MIN_OPTIONS:
                resultados_anterior = db_carregar_resultados(num_opcoes_anterior)
                db_adicionar_ao_historico(
                    dados_enquete_anterior["pergunta"],
                    dados_enquete_anterior["opcoes"],
                    resultados_anterior["votos"],
                    resultados_anterior["total_votos"],
                )
        opcoes_finais = [opt.strip() for opt in opcoes_form_inputs[: st.session_state.num_opcoes_edicao]]
        opcoes_validas_count = sum(1 for opt in opcoes_finais if opt)
        if not pergunta_form.strip() or opcoes_validas_count < MIN_OPTIONS:
            st.error(f"A pergunta não pode ser vazia e deve haver pelo menos {MIN_OPTIONS} opções preenchidas.")
        else:
            db_salvar_dados_enquete(pergunta_form, opcoes_finais)
            db_salvar_config_valor("enquete_ativa", True)
            db_limpar_votos_e_cookies(len(opcoes_finais))
            st.success("Enquete salva, ativada e votos resetados!")
            st.rerun()

    if enquete_ativa_db:
        if st.button("Desativar Enquete", key="painel_desativar_db_vfinal"):
            dados_enquete_a_desativar = db_carregar_dados_enquete()
            if dados_enquete_a_desativar.get("pergunta", "").strip():
                num_opcoes_desativada = len(dados_enquete_a_desativar.get("opcoes", []))
                if num_opcoes_desativada >= MIN_OPTIONS:
                    resultados_desativada = db_carregar_resultados(num_opcoes_desativada)
                    db_adicionar_ao_historico(
                        dados_enquete_a_desativar["pergunta"],
                        dados_enquete_a_desativar["opcoes"],
                        resultados_desativada["votos"],
                        resultados_desativada["total_votos"],
                    )
            db_salvar_config_valor("enquete_ativa", False)
            num_opcoes_calc = len(dados_enquete_a_desativar.get("opcoes", []))
            db_limpar_votos_e_cookies(max(MIN_OPTIONS, num_opcoes_calc))
            st.success("Enquete desativada, resultados arquivados e votos resetados!")
            st.rerun()

    st.subheader("Status da Enquete")
    enquete_ativa_status = db_carregar_config_valor("enquete_ativa", False)
    if enquete_ativa_status:
        st.success("Enquete ATIVA")
    else:
        st.error("Enquete INATIVA")

    st.subheader("Resultados da Votação")
    if enquete_ativa_status:
        dados_atuais = db_carregar_dados_enquete()
        num_opcoes_resultados = len(dados_atuais.get("opcoes", []))
        if num_opcoes_resultados > 0:
            resultados_display = db_carregar_resultados(num_opcoes_resultados)
            mostrar_resultados(dados_atuais, resultados_display)
        else:
            st.info("A enquete ativa não possui opções configuradas.")
        time.sleep(5)
        st.rerun()
    else:
        st.info("A enquete está inativa. Ative-a para ver os resultados ou permitir novos votos.")


def mostrar_tela_alterar_senha():
    st.title("🔑 Alterar Senha do Professor")
    with st.form("alt_senha_frm_vfinal"):
        nova_senha = st.text_input("Nova Senha", type="password", key="alt_nova_senha_vfinal")
        confirmar = st.text_input("Confirmar Nova Senha", type="password", key="alt_confirma_vfinal")
        submit = st.form_submit_button("Confirmar Alteração")
        if submit:
            if not nova_senha or not confirmar:
                st.error("Campos não podem ser vazios.")
            elif nova_senha != confirmar:
                st.error("Senhas não coincidem.")
            elif len(nova_senha) < 6:
                st.error("Senha curta (mínimo 6 caracteres).")
            else:
                db_salvar_config_valor("senha_professor", hash_password(nova_senha))
                st.success("Senha alterada com sucesso!")
                st.session_state.pagina_professor = "painel"
                st.rerun()
    st.divider()
    if st.button("Voltar ao Painel", key="alt_voltar_vfinal"):
        st.session_state.pagina_professor = "painel"
        st.rerun()


def mostrar_tela_aluno():
    if "user_voting_id" not in st.session_state or not st.session_state.user_voting_id:
        st.info("⌛ Identificador de votação da sessão sendo preparado... Por favor, aguarde um momento.")
        return

    config_enquete_ativa = db_carregar_config_valor("enquete_ativa", False)
    if not config_enquete_ativa:
        st.title("⌛ Aguardando Nova Enquete...")
        st.info("Nenhuma enquete ativa no momento. Use o botão 🔄 no Menu lateral para verificar")
        return

    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_enquete_lista = dados_enquete_db.get("opcoes", [])
    num_opcoes_atual = len(opcoes_enquete_lista)

    if not dados_enquete_db.get("pergunta", "").strip() or num_opcoes_atual < MIN_OPTIONS:
        st.title("⌛ Enquete em Configuração")
        st.info("A enquete atual ainda não está pronta. Por favor, aguarde.")
        return

    resultados_db = db_carregar_resultados(num_opcoes_atual)

    user_id_for_vote = st.session_state.user_voting_id
    ja_votou_db = db_verificar_se_cookie_votou(user_id_for_vote)
    st.session_state.voto_registrado_nesta_sessao = ja_votou_db

    st.title("📊 Participe da enquete")
    st.header(dados_enquete_db.get("pergunta", "Enquete sem pergunta definida"))

    if st.session_state.voto_registrado_nesta_sessao:
        st.success("🙂 Seu voto foi registrado na enquete! Por favor aguarde os demais colegas votarem...")
        mostrar_resultados(dados_enquete_db, resultados_db)
        time.sleep(7)
        st.rerun()
    else:
        opcoes_validas_aluno = [opt for opt in opcoes_enquete_lista if opt and opt.strip()]
        if not opcoes_validas_aluno:
            st.warning("A enquete não possui opções válidas no momento.")
            return

        if len(opcoes_validas_aluno) != len(set(opcoes_validas_aluno)):
            opcoes_display = [f"{opt} ({i+1})" if opcoes_validas_aluno.count(opt) > 1 else opt for i, opt in enumerate(opcoes_validas_aluno)]
        else:
            opcoes_display = opcoes_validas_aluno

        key_radio = f"voto_radio_{hashlib.md5(json.dumps(opcoes_validas_aluno).encode()).hexdigest()}"
        indice_escolhido = st.radio(
            "Escolha uma opção:",
            range(len(opcoes_display)),
            format_func=lambda i: opcoes_display[i],
            key=key_radio,
        )

        if st.button("Votar", key="aluno_votar_db_vfinal_cookie"):
            if not user_id_for_vote:
                st.error("Falha ao verificar sua identificação. Por favor, recarregue a página.")
                return

            if db_verificar_se_cookie_votou(user_id_for_vote):
                st.warning("Voto já registrado para este dispositivo/navegador.")
                st.session_state.voto_registrado_nesta_sessao = True
                st.rerun()
                return

            if indice_escolhido is not None:
                opcao_original = opcoes_validas_aluno[indice_escolhido]
                try:
                    indice_real = opcoes_enquete_lista.index(opcao_original)
                except ValueError:
                    st.error("Opção inválida. Tente novamente.")
                    return

                if db_registrar_voto(indice_real, user_id_for_vote):
                    st.session_state.voto_registrado_nesta_sessao = True
                    st.success("Voto registrado com sucesso!")
                    st.rerun()
                else:
                    st.error("Erro: Voto já registrado ou opção inválida.")
                    st.session_state.voto_registrado_nesta_sessao = True
                    st.rerun()
            else:
                st.warning("Selecione uma opção.")


def mostrar_resultados(dados_enquete_param, resultados_param):
    total_votos = resultados_param.get("total_votos", 0)
    opcoes = dados_enquete_param.get("opcoes", [])
    if not opcoes:
        st.info("Não há opções definidas para esta enquete.")
        return
    if total_votos == 0:
        st.info("Ainda não há votos registrados.")
        return

    votos = list(resultados_param.get("votos", []))
    num_opcoes = len(opcoes)

    if len(votos) < num_opcoes:
        votos.extend([0] * (num_opcoes - len(votos)))
    elif len(votos) > num_opcoes:
        votos = votos[:num_opcoes]

    st.write(f"**Total de votos: {total_votos}**")
    for i, opt_txt in enumerate(opcoes):
        if opt_txt and opt_txt.strip():
            v_count = votos[i] if i < len(votos) else 0
            perc = (v_count / total_votos) * 100 if total_votos > 0 else 0
            st.write(f"**{opt_txt}**: {v_count} ({perc:.1f}%)")
            st.progress(min(perc / 100.0, 1.0))


def mostrar_enquete_historico(id_historico):
    dados_enquete = db_carregar_enquete_historico_por_id(id_historico)
    if not dados_enquete:
        st.error("Enquete não encontrada no histórico.")
        if st.button("⬅️ Voltar à página principal", key="voltar_hist_err"):
            st.query_params.clear()
            st.rerun()
        return

    st.title("📜 Histórico da Enquete")
    st.subheader(f"Pergunta: {dados_enquete['pergunta']}")
    st.caption(f"Realizada em: {format_timestamp_br(dados_enquete['timestamp'])}")
    st.divider()

    total_votos_hist = dados_enquete.get("total_votos", 0)
    opcoes_hist = dados_enquete.get("opcoes", [])
    votos_hist = list(dados_enquete.get("votos", []))

    if not opcoes_hist:
        st.info("Não há opções definidas para esta enquete do histórico.")
    elif total_votos_hist == 0:
        st.info("Não houve votos registrados para esta enquete.")
    else:
        num_opcoes_hist = len(opcoes_hist)
        if len(votos_hist) < num_opcoes_hist:
            votos_hist.extend([0] * (num_opcoes_hist - len(votos_hist)))
        elif len(votos_hist) > num_opcoes_hist:
            votos_hist = votos_hist[:num_opcoes_hist]

        st.write(f"**Total de votos: {total_votos_hist}**")
        for i, opt_txt in enumerate(opcoes_hist):
            if opt_txt and opt_txt.strip():
                v_count = votos_hist[i] if i < len(votos_hist) else 0
                perc = (v_count / total_votos_hist) * 100 if total_votos_hist > 0 else 0
                st.write(f"**{opt_txt}**: {v_count} ({perc:.1f}%)")
                st.progress(min(perc / 100.0, 1.0))

    st.divider()
    if st.button("⬅️ Voltar à página principal", key="voltar_hist_main"):
        st.query_params.clear()
        st.rerun()


# --- Router Principal ---
def app_router():
    initialize_session_state()
    _init_db_once()

    if "user_voting_id" not in st.session_state:
        st.session_state.user_voting_id = str(uuid.uuid4())
        st.rerun()
        return

    page_param = st.query_params.get("page", None)
    enquete_id_param_list = st.query_params.get_all("enquete_id")
    enquete_id_param = enquete_id_param_list[0] if enquete_id_param_list else None

    if page_param == "historico_view":
        if enquete_id_param:
            try:
                mostrar_enquete_historico(int(enquete_id_param))
                return
            except ValueError:
                st.error("ID de enquete do histórico inválido.")
                if st.button("⬅️ Voltar"):
                    st.query_params.clear()
                    st.rerun()
                return
        else:
            st.warning("ID da enquete do histórico não fornecido.")
            if st.button("⬅️ Voltar"):
                st.query_params.clear()
                st.rerun()
            return

    with st.sidebar:
        st.title("Menu")
        if st.button("Professor", key="sidebar_prof_vfinal", use_container_width=True):
            current_mode = st.session_state.get("modo")
            if current_mode not in ("professor", "login_professor"):
                st.query_params.clear()
                st.session_state.modo = "login_professor"
                st.session_state.pagina_professor = "painel"
                st.rerun()
            elif current_mode == "login_professor":
                st.query_params.clear()
                st.rerun()

        if st.session_state.modo != "professor":
            col_sb1, col_sb2 = st.columns([3, 2])
            with col_sb1:
                if st.button("Aluno", key="sidebar_aluno_vfinal", use_container_width=True):
                    if st.session_state.modo != "aluno":
                        st.query_params.clear()
                        st.session_state.modo = "aluno"
                        st.rerun()
            with col_sb2:
                if st.session_state.modo == "aluno":
                    if st.button("🔄", key="sidebar_recarregar_vfinal", help="Recarregar enquete/resultados", use_container_width=True):
                        st.rerun()

        st.divider()
        st.title("Histórico")
        historico_enquetes = db_carregar_historico(limite=HISTORICO_LIMIT)
        if historico_enquetes:
            for item_hist in historico_enquetes:
                pergunta_raw = item_hist["pergunta"]
                pergunta_curta = pergunta_raw[:25] + "..." if len(pergunta_raw) > 25 else pergunta_raw
                pergunta_escaped = html_module.escape(pergunta_curta)
                ts_formatado = format_timestamp_br_short(item_hist["timestamp"])
                link_html = (
                    f"<a href='?page=historico_view&enquete_id={int(item_hist['id'])}' target='_self'>"
                    f"📊 {pergunta_escaped} ({ts_formatado})</a>"
                )
                st.markdown(f"<div class='sidebar-history-link'>{link_html}</div>", unsafe_allow_html=True)
        else:
            st.sidebar.caption("Nenhuma enquete no histórico")

    modo_atual = st.session_state.get("modo")
    if modo_atual == "login_professor":
        mostrar_tela_login()
    elif modo_atual == "professor":
        if st.session_state.pagina_professor == "painel":
            mostrar_painel_professor()
        elif st.session_state.pagina_professor == "alterar_senha":
            mostrar_tela_alterar_senha()
        else:
            st.session_state.pagina_professor = "painel"
            st.rerun()
    elif modo_atual == "aluno":
        mostrar_tela_aluno()
    else:
        st.session_state.modo = "aluno"
        st.rerun()

    st.markdown(
        '<hr><div style="text-align:center; margin-top:40px; padding:10px; color:#000000; font-size:16px;">'
        "<h4>📊 Enquete App</h4>Sua enquete em tempo real<br>"
        'Por <strong>Ary Ribeiro:</strong> <a href="mailto:aryribeiro@gmail.com">aryribeiro@gmail.com</a></div>',
        unsafe_allow_html=True,
    )



if __name__ == "__main__":
    app_router()
