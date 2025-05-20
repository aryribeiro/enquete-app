# app.py
import streamlit as st
import pandas as pd
import time
from datetime import datetime
from zoneinfo import ZoneInfo 
import hashlib
import json
import sqlite3
from streamlit.components.v1 import html
import uuid

# --- Configurações Globais e Constantes ---
DB_NAME = "enquete_app_vfinal_cookie.db" 
MIN_OPTIONS = 2
MAX_OPTIONS = 10
DEFAULT_NUM_OPTIONS_ON_NEW = 2
HISTORICO_LIMIT = 5

# --- CSS Styling ---
st.set_page_config(
    page_title="Enquete App | Sua enquete em tempo real",
    page_icon="📊",
    layout="centered",
)
st.markdown("""
<style>
    .main { background-color: #ffffff; color: #333333; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    header, footer, #MainMenu { display: none !important; }
    div[data-testid="stAppViewBlockContainer"], div[data-testid="stVerticalBlock"] {
        padding-top: 0 !important; padding-bottom: 0 !important; gap: 0 !important;
    }
    .element-container { margin-top: 0 !important; margin-bottom: 0 !important; }
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
""", unsafe_allow_html=True)

# --- Funções Utilitárias ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# --- Funções de Banco de Dados (SQLite) ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    admin_password_default = "admin123"
    admin_password_hash = hash_password(admin_password_default)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracao (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('senha_professor', admin_password_hash))
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('enquete_ativa', '0'))
    
    # Corrigido: Armazenar datetime como string ISO para evitar DeprecationWarning
    config_ts_utc_iso = datetime.now(ZoneInfo("UTC")).isoformat()
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', config_ts_utc_iso)) 
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_definicao (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        pergunta TEXT,
        opcoes_json TEXT
    )
    """)
    default_opcoes_json = json.dumps([""] * DEFAULT_NUM_OPTIONS_ON_NEW)
    cursor.execute("INSERT OR IGNORE INTO enquete_ativa_definicao (id, pergunta, opcoes_json) VALUES (1, ?, ?)", 
                   ('', default_opcoes_json))
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
        timestamp TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'NOW')), -- Armazena como string ISO UTC
        pergunta TEXT NOT NULL,
        opcoes_json TEXT NOT NULL,
        votos_json TEXT NOT NULL,
        total_votos INTEGER DEFAULT 0
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historico_timestamp ON historico_enquetes (timestamp DESC);")
    conn.commit()
    conn.close()

def db_adicionar_ao_historico(pergunta, opcoes_lista, votos_lista, total_votos_final):
    if not pergunta or not opcoes_lista:
        st.warning("Tentativa de salvar enquete vazia no histórico. Operação ignorada.")
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    opcoes_json_str = json.dumps(opcoes_lista)
    votos_json_str = json.dumps(votos_lista)
    try:
        cursor.execute("""
            INSERT INTO historico_enquetes (pergunta, opcoes_json, votos_json, total_votos)
            VALUES (?, ?, ?, ?)
        """, (pergunta, opcoes_json_str, votos_json_str, total_votos_final))
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao salvar enquete no histórico: {e}")
    finally:
        conn.close()
    db_manter_limite_historico()

def db_manter_limite_historico(limite=HISTORICO_LIMIT):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as count FROM historico_enquetes")
        count_row = cursor.fetchone()
        if count_row and count_row['count'] > limite:
            num_to_delete = count_row['count'] - limite
            cursor.execute("""
                DELETE FROM historico_enquetes
                WHERE id IN (
                    SELECT id FROM historico_enquetes
                    ORDER BY timestamp ASC, id ASC
                    LIMIT ?
                )
            """, (num_to_delete,))
            conn.commit()
    except sqlite3.Error as e:
        st.error(f"Erro ao manter limite do histórico: {e}")
    finally:
        conn.close()

def db_carregar_historico(limite=HISTORICO_LIMIT):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, pergunta, timestamp FROM historico_enquetes
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """, (limite,))
        historico = cursor.fetchall() 
        return historico
    except sqlite3.Error as e:
        st.error(f"Erro ao carregar histórico: {e}")
        return []
    finally:
        conn.close()

def db_carregar_enquete_historico_por_id(id_historico):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT pergunta, opcoes_json, votos_json, total_votos, timestamp FROM historico_enquetes WHERE id = ?", (id_historico,))
        enquete_data = cursor.fetchone() 
        if enquete_data:
            return {
                "pergunta": enquete_data["pergunta"],
                "opcoes": json.loads(enquete_data["opcoes_json"]),
                "votos": json.loads(enquete_data["votos_json"]),
                "total_votos": enquete_data["total_votos"],
                "timestamp": enquete_data["timestamp"] 
            }
        return None
    except (sqlite3.Error, json.JSONDecodeError) as e:
        st.error(f"Erro ao carregar enquete do histórico por ID: {e}")
        return None
    finally:
        conn.close()

def db_carregar_config_valor(chave, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM configuracao WHERE chave = ?", (chave,))
    row = cursor.fetchone()
    conn.close()
    if row:
        if chave == 'enquete_ativa':
            return True if row['valor'] == '1' else False
        return row['valor']
    return default

def db_salvar_config_valor(chave, valor):
    conn = get_db_connection()
    cursor = conn.cursor()
    valor_db = valor
    if chave == 'enquete_ativa':
        valor_db = '1' if valor else '0'
    
    # Salva a chave/valor específica
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", (chave, valor_db))
    
    # Sempre atualiza 'ultima_atualizacao_config' com o timestamp UTC ISO formatado
    update_ts_utc_iso = datetime.now(ZoneInfo("UTC")).isoformat()
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', update_ts_utc_iso))
    conn.commit()
    conn.close()

def db_carregar_dados_enquete():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pergunta, opcoes_json FROM enquete_ativa_definicao WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row and row["opcoes_json"]:
        try:
            opcoes = json.loads(row["opcoes_json"])
            return {"pergunta": row["pergunta"], "opcoes": opcoes}
        except json.JSONDecodeError:
            pass
    return {"pergunta": "", "opcoes": [""] * DEFAULT_NUM_OPTIONS_ON_NEW}

def db_salvar_dados_enquete(pergunta, opcoes_lista):
    opcoes_json_str = json.dumps(opcoes_lista)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO enquete_ativa_definicao (id, pergunta, opcoes_json) VALUES (1, ?, ?)",
                   (pergunta, opcoes_json_str))
    conn.commit()
    conn.close()
    db_salvar_config_valor('enquete_definicao_modificada', 'true') # Apenas para triggar a atualização do timestamp

def db_limpar_votos_e_cookies(num_opcoes_enquete_atual):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM enquete_ativa_votos")
    cursor.execute("DELETE FROM enquete_ativa_cookie_votantes")
    num_opcoes_valido = max(MIN_OPTIONS, min(num_opcoes_enquete_atual, MAX_OPTIONS))
    for i in range(num_opcoes_valido):
        cursor.execute("INSERT INTO enquete_ativa_votos (opcao_indice, contagem) VALUES (?, 0)", (i,))
    conn.commit()
    conn.close()

def db_carregar_resultados(num_opcoes_enquete_atual):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT opcao_indice, contagem FROM enquete_ativa_votos ORDER BY opcao_indice ASC")
    votos_rows = cursor.fetchall()
    cursor.execute("SELECT SUM(contagem) as total_votos FROM enquete_ativa_votos")
    total_votos_row = cursor.fetchone()
    conn.close()
    total_votos = total_votos_row['total_votos'] if total_votos_row and total_votos_row['total_votos'] is not None else 0
    votos_lista = [0] * num_opcoes_enquete_atual
    for row in votos_rows:
        if 0 <= row['opcao_indice'] < num_opcoes_enquete_atual:
            votos_lista[row['opcao_indice']] = row['contagem']
    return {"votos": votos_lista, "total_votos": total_votos}

def db_registrar_voto(opcao_indice, user_voting_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Corrigido: Armazenar datetime como string ISO para evitar DeprecationWarning
        vote_ts_utc_iso = datetime.now(ZoneInfo("UTC")).isoformat()
        cursor.execute("INSERT INTO enquete_ativa_cookie_votantes (user_voting_id, vote_timestamp) VALUES (?, ?)", 
                       (user_voting_id, vote_ts_utc_iso))
        cursor.execute("UPDATE enquete_ativa_votos SET contagem = contagem + 1 WHERE opcao_indice = ?", (opcao_indice,))
        conn.commit()
        return True
    except sqlite3.IntegrityError: 
        return False 
    finally:
        conn.close()

def db_verificar_se_cookie_votou(user_voting_id): 
    if not user_voting_id:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM enquete_ativa_cookie_votantes WHERE user_voting_id = ?", (user_voting_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def initialize_session_state():
    defaults = {
        'modo': 'aluno', 
        'voto_registrado_nesta_sessao': False, 
        'pagina_professor': 'painel',
        'num_opcoes_edicao': DEFAULT_NUM_OPTIONS_ON_NEW,
    }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value

def mostrar_tela_login():
    st.title("🔐 Login do Professor")
    senha_digitada = st.text_input("Senha", type="password", key="login_senha_vfinal")
    if st.button("Entrar", key="login_entrar_vfinal"):
        senha_hash_db = db_carregar_config_valor("senha_professor")
        if senha_hash_db and hash_password(senha_digitada) == senha_hash_db:
            st.session_state.modo = 'professor'
            st.session_state.pagina_professor = 'painel'
            st.success("Login realizado com sucesso!")
            st.rerun()
        else:
            st.error("Senha incorreta!")

def mostrar_painel_professor():
    st.title("🖥️ Painel do Professor")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🔐 Alterar Senha", key="painel_btn_alt_senha", use_container_width=True):
            st.session_state.pagina_professor = 'alterar_senha'
            st.rerun()
            return
    with col_nav2:
        if st.button("🚪 Logout", key="painel_btn_logout", use_container_width=True):
            st.session_state.modo = 'login_professor'
            st.session_state.pagina_professor = 'painel'
            st.session_state.voto_registrado_nesta_sessao = False 
            st.rerun()
            return
    st.divider()

    enquete_ativa_db = db_carregar_config_valor('enquete_ativa', False)
    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_salvas = dados_enquete_db.get("opcoes", [])
    num_opcoes_atuais = len(opcoes_salvas) if opcoes_salvas else st.session_state.num_opcoes_edicao
    if 'num_opcoes_edicao_loaded' not in st.session_state or st.session_state.num_opcoes_edicao_loaded != num_opcoes_atuais:
        st.session_state.num_opcoes_edicao = max(MIN_OPTIONS, min(num_opcoes_atuais, MAX_OPTIONS))
        st.session_state.num_opcoes_edicao_loaded = num_opcoes_atuais
    
    num_opcoes_widget_key = "prof_num_opcoes_selector_v2" 
    if num_opcoes_widget_key not in st.session_state:
      st.session_state[num_opcoes_widget_key] = st.session_state.num_opcoes_edicao

    def update_num_opcoes_edicao():
        st.session_state.num_opcoes_edicao = st.session_state[num_opcoes_widget_key]
        st.session_state.num_opcoes_edicao_loaded = st.session_state[num_opcoes_widget_key]

    num_opcoes_widget = st.number_input(
        "Número de Opções de Resposta:", min_value=MIN_OPTIONS, max_value=MAX_OPTIONS,
        key=num_opcoes_widget_key,
        on_change=update_num_opcoes_edicao 
    )
    if st.session_state.num_opcoes_edicao != num_opcoes_widget:
         st.session_state.num_opcoes_edicao = num_opcoes_widget
         st.session_state.num_opcoes_edicao_loaded = num_opcoes_widget

    st.subheader("Gerenciar Enquete")
    with st.form("painel_enquete_form_db_vfinal"):
        pergunta_form = st.text_input("Pergunta da Enquete", value=dados_enquete_db.get("pergunta", ""), key="painel_pergunta_db_vfinal")
        st.write(f"Opções de Resposta ({st.session_state.num_opcoes_edicao} opções):")
        opcoes_form_inputs = [""] * st.session_state.num_opcoes_edicao
        for i in range(st.session_state.num_opcoes_edicao):
            val_opt = opcoes_salvas[i] if i < len(opcoes_salvas) else ""
            opcoes_form_inputs[i] = st.text_input(f"Opção {i+1}", value=val_opt, key=f"painel_opt_db_vfinal_{i}")
        submit_save_enquete = st.form_submit_button("Salvar e Ativar Enquete")
    
    if submit_save_enquete:
        dados_enquete_anterior = db_carregar_dados_enquete()
        enquete_estava_ativa_anteriormente = db_carregar_config_valor('enquete_ativa', False)
        if enquete_estava_ativa_anteriormente and dados_enquete_anterior.get("pergunta","").strip():
            num_opcoes_anterior = len(dados_enquete_anterior.get("opcoes", []))
            if num_opcoes_anterior >= MIN_OPTIONS:
                resultados_anterior = db_carregar_resultados(num_opcoes_anterior)
                db_adicionar_ao_historico(
                    dados_enquete_anterior["pergunta"],
                    dados_enquete_anterior["opcoes"],
                    resultados_anterior["votos"],
                    resultados_anterior["total_votos"]
                )
        opcoes_finais_para_salvar = [opt.strip() for opt in opcoes_form_inputs[:st.session_state.num_opcoes_edicao]]
        opcoes_validas_count = sum(1 for opt in opcoes_finais_para_salvar if opt)
        if not pergunta_form.strip() or opcoes_validas_count < MIN_OPTIONS:
            st.error(f"A pergunta não pode ser vazia e deve haver pelo menos {MIN_OPTIONS} opções preenchidas.")
        else:
            db_salvar_dados_enquete(pergunta_form, opcoes_finais_para_salvar)
            db_salvar_config_valor('enquete_ativa', True)
            db_limpar_votos_e_cookies(len(opcoes_finais_para_salvar)) 
            st.success("Enquete salva, ativada e votos resetados!")
            st.rerun()

    if enquete_ativa_db:
        if st.button("Desativar Enquete", key="painel_desativar_db_vfinal"):
            dados_enquete_a_desativar = db_carregar_dados_enquete()
            if dados_enquete_a_desativar.get("pergunta","").strip():
                num_opcoes_desativada = len(dados_enquete_a_desativar.get("opcoes", []))
                if num_opcoes_desativada >= MIN_OPTIONS:
                    resultados_desativada = db_carregar_resultados(num_opcoes_desativada)
                    db_adicionar_ao_historico(
                        dados_enquete_a_desativar["pergunta"],
                        dados_enquete_a_desativar["opcoes"],
                        resultados_desativada["votos"],
                        resultados_desativada["total_votos"]
                    )
            db_salvar_config_valor('enquete_ativa', False)
            num_opcoes_enq_desativada_calc = len(dados_enquete_a_desativar.get("opcoes", []))
            db_limpar_votos_e_cookies(max(MIN_OPTIONS, num_opcoes_enq_desativada_calc)) 
            st.success("Enquete desativada, resultados arquivados e votos resetados!")
            st.rerun()
            
    st.subheader("Status da Enquete")
    enquete_ativa_status_display = db_carregar_config_valor('enquete_ativa', False)
    if enquete_ativa_status_display:
        st.success("Enquete ATIVA")
    else:
        st.error("Enquete INATIVA")
        
    st.subheader("Resultados da Votação")
    if enquete_ativa_status_display:
        dados_enquete_atuais_resultados = db_carregar_dados_enquete()
        num_opcoes_resultados = len(dados_enquete_atuais_resultados.get("opcoes",[]))
        if num_opcoes_resultados > 0:
            resultados_db_display = db_carregar_resultados(num_opcoes_resultados)
            mostrar_resultados(dados_enquete_atuais_resultados, resultados_db_display, refresh=True)
        else:
            st.info("A enquete ativa não possui opções configuradas.")
    else:
        st.info("A enquete está inativa. Ative-a para ver os resultados ou permitir novos votos.")
    
    if enquete_ativa_status_display:
        time.sleep(5) 
        st.rerun()

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
                db_salvar_config_valor('senha_professor', hash_password(nova_senha))
                st.success("Senha alterada! Retornando ao painel...")
                time.sleep(1.5)
                st.session_state.pagina_professor = 'painel'
                st.rerun()
    st.divider()
    if st.button("Voltar ao Painel", key="alt_voltar_vfinal"):
        st.session_state.pagina_professor = 'painel'
        st.rerun()

def mostrar_tela_aluno():
    if 'user_voting_id' not in st.session_state or not st.session_state.user_voting_id:
        st.info("⌛ Identificador de votação da sessão sendo preparado... Por favor, aguarde um momento.")
        return 

    config_enquete_ativa = db_carregar_config_valor('enquete_ativa', False)
    if not config_enquete_ativa:
        st.title("⌛ Aguardando Nova Enquete...")
        st.info("Nenhuma enquete ativa no momento. Use o botão 🔄 no Menu lateral para verificar")
        return

    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_enquete_lista = dados_enquete_db.get("opcoes", [])
    num_opcoes_atual = len(opcoes_enquete_lista)

    if not dados_enquete_db.get("pergunta","").strip() or num_opcoes_atual < MIN_OPTIONS:
        st.title("⌛ Enquete em Configuração")
        st.info("A enquete atual ainda não está pronta. Por favor, aguarde.")
        return

    resultados_db = db_carregar_resultados(num_opcoes_atual)
    
    user_id_for_vote = st.session_state.user_voting_id
    ja_votou_db = db_verificar_se_cookie_votou(user_id_for_vote)
    st.session_state.voto_registrado_nesta_sessao = ja_votou_db

    st.title("📊 Participe da enquete")
    st.header(dados_enquete_db.get("pergunta","Enquete sem pergunta definida"))
    
    js_check_hourly_cookie = """
        <div id="hourly-vote-cookie-message" style="display:none; color: #000000; margin-bottom: 10px; padding: 10px; border: 1px solid #28a745; border-radius: 5px;"></div>
        <script>
            function getCookie(name) {
                var nameEQ = name + "=";
                var ca = document.cookie.split(';');
                for(var i=0;i < ca.length;i++) {
                    var c = ca[i];
                    while (c.charAt(0)==' ') c = c.substring(1,c.length);
                    if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
                }
                return null;
            }
            var votedRecentlyCookie = getCookie("voted_current_active_poll_v2");
            var messageDiv = document.getElementById('hourly-vote-cookie-message');
            if (votedRecentlyCookie === "true" && messageDiv) {
                messageDiv.innerHTML = "...SEJA BEM-VINDO(A) DE VOLTA AO WEB APP <strong>ENQUETE APP</strong>! VOTE E AGUARDE OS D+";
                messageDiv.style.display = 'block';
            }
        </script>
    """
    if not st.session_state.voto_registrado_nesta_sessao : 
        html(js_check_hourly_cookie, height=50) 

    if st.session_state.voto_registrado_nesta_sessao:
        st.success("🙂 Seu voto foi registrado na enquete! Por favor aguarde os demais colegas votarem...")
        mostrar_resultados(dados_enquete_db, resultados_db, refresh=config_enquete_ativa)
    else:
        opcoes_validas_aluno = [opt for opt in opcoes_enquete_lista if opt and opt.strip()]
        if not opcoes_validas_aluno:
            st.warning("A enquete não possui opções válidas no momento.")
            return

        key_radio_aluno = f"voto_radio_db_vfinal_cookie_{hashlib.md5(json.dumps(opcoes_validas_aluno).encode()).hexdigest()}"
        opcao_escolhida_aluno = st.radio("Escolha uma opção:", opcoes_validas_aluno, key=key_radio_aluno)
        
        if st.button("Votar", key="aluno_votar_db_vfinal_cookie"):
            if not user_id_for_vote: 
                st.error("Falha ao verificar sua identificação. Por favor, recarregue a página.")
                return

            if db_verificar_se_cookie_votou(user_id_for_vote):
                st.warning("Voto já registrado para este dispositivo/navegador (verificação de banco de dados).")
                st.session_state.voto_registrado_nesta_sessao = True
                st.rerun()
                return

            if opcao_escolhida_aluno:
                try:
                    indice_opcao_votada = opcoes_enquete_lista.index(opcao_escolhida_aluno)
                    if db_registrar_voto(indice_opcao_votada, user_id_for_vote):
                        st.session_state.voto_registrado_nesta_sessao = True
                        js_set_hourly_cookie = """
                            <script>
                                function setCookie(name, value, hours) {
                                    var expires = "";
                                    if (hours) {
                                        var date = new Date();
                                        date.setTime(date.getTime() + (hours*60*60*1000));
                                        expires = "; expires=" + date.toUTCString();
                                    }
                                    document.cookie = name + "=" + (value || "")  + expires + "; path=/";
                                }
                                setCookie("voted_current_active_poll_v2", "true", 1); 
                            </script>
                        """
                        html(js_set_hourly_cookie, height=0)
                        st.success("Voto registrado com sucesso!")
                        time.sleep(1) 
                        st.rerun()
                    else:
                        st.error("Erro: Voto já registrado (verificação de banco de dados).")
                        st.session_state.voto_registrado_nesta_sessao = True
                        st.rerun()
                except ValueError:
                    st.error("Opção inválida. Tente novamente.")
                except Exception as e:
                    st.error(f"Erro ao votar: {e}")
            else:
                st.warning("Selecione uma opção.")

def mostrar_resultados(dados_enquete_param, resultados_param, refresh=False):
    total_votos_param = resultados_param.get("total_votos", 0)
    opcoes_da_enquete_param = dados_enquete_param.get("opcoes", [])
    if not opcoes_da_enquete_param:
        st.info("Não há opções definidas para esta enquete.")
        return
    if total_votos_param == 0:
        st.info("Ainda não há votos registrados.")
        return
        
    votos_registrados_param = resultados_param.get("votos", [])
    num_opcoes_atual_param = len(opcoes_da_enquete_param)

    if len(votos_registrados_param) < num_opcoes_atual_param:
        votos_registrados_param.extend([0] * (num_opcoes_atual_param - len(votos_registrados_param)))
    elif len(votos_registrados_param) > num_opcoes_atual_param:
        votos_registrados_param = votos_registrados_param[:num_opcoes_atual_param]

    dados_para_df_param = []
    for i, opt_txt_param in enumerate(opcoes_da_enquete_param):
        if opt_txt_param and opt_txt_param.strip(): 
            v_count_param = votos_registrados_param[i] if i < len(votos_registrados_param) else 0
            perc_param = (v_count_param / total_votos_param) * 100 if total_votos_param > 0 else 0
            dados_para_df_param.append({"opcao": opt_txt_param, "votos": v_count_param, "percentual": perc_param})
    
    if not dados_para_df_param:
        st.info("Sem dados de votação válidos para exibir.")
        return

    df_param = pd.DataFrame(dados_para_df_param)
    st.write(f"**Total de votos: {total_votos_param}**")
    
    for _, row_param in df_param.iterrows():
        st.write(f"**{row_param['opcao']}**: {row_param['votos']} ({row_param['percentual']:.1f}%)")
        st.progress(int(row_param["percentual"])) 

    if refresh:
        is_student_mode_active_poll = (st.session_state.modo == 'aluno' and 
                                       db_carregar_config_valor('enquete_ativa', False))
        
        if st.session_state.modo == 'professor' or is_student_mode_active_poll :
            refresh_interval = 7 if is_student_mode_active_poll else 5 
            time.sleep(refresh_interval)
            st.rerun()

def mostrar_enquete_historico(id_historico):
    utc_tz = ZoneInfo("UTC")
    br_tz = ZoneInfo("America/Sao_Paulo")

    dados_enquete = db_carregar_enquete_historico_por_id(id_historico)
    if dados_enquete:
        st.title("📜 Histórico da Enquete")
        st.subheader(f"Pergunta: {dados_enquete['pergunta']}")
        
        ts_caption_formatado = "Data não disponível" 
        if dados_enquete['timestamp']:
            timestamp_str = dados_enquete['timestamp']
            try:
                # SQLite STRFTIME com '%Y-%m-%dT%H:%M:%fZ' é compatível com fromisoformat
                # datetime.fromisoformat espera que 'Z' seja +00:00 ou ausente para naive.
                # Se 'Z' estiver presente, é UTC.
                if timestamp_str.endswith('Z'):
                    utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else: # Assume que é uma string naive que representa UTC ou já tem offset
                    naive_dt = datetime.fromisoformat(timestamp_str)
                    if naive_dt.tzinfo is None:
                        utc_dt = naive_dt.replace(tzinfo=utc_tz)
                    else: # Já é timezone-aware
                        utc_dt = naive_dt.astimezone(utc_tz)

                br_dt = utc_dt.astimezone(br_tz)
                ts_caption_formatado = br_dt.strftime('%d/%m/%Y %H:%M:%S')
            except ValueError: # Fallback para formatos não-ISO
                try:
                    naive_dt = datetime.strptime(timestamp_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                    utc_dt = naive_dt.replace(tzinfo=utc_tz)
                    br_dt = utc_dt.astimezone(br_tz)
                    ts_caption_formatado = br_dt.strftime('%d/%m/%Y %H:%M:%S')
                except ValueError:
                    ts_caption_formatado = timestamp_str.split('.')[0] # Último fallback

        st.caption(f"Realizada em: {ts_caption_formatado}")
        st.divider()

        total_votos_hist = dados_enquete.get("total_votos", 0)
        opcoes_hist = dados_enquete.get("opcoes", [])
        votos_hist = dados_enquete.get("votos", [])

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
            
            dados_df_hist = []
            for i, opt_txt in enumerate(opcoes_hist):
                if opt_txt and opt_txt.strip():
                    v_count = votos_hist[i] if i < len(votos_hist) else 0
                    perc = (v_count / total_votos_hist) * 100 if total_votos_hist > 0 else 0
                    dados_df_hist.append({"opcao": opt_txt, "votos": v_count, "percentual": perc})
            
            if not dados_df_hist:
                st.info("Sem dados de votação válidos para exibir do histórico.")
            else:
                df_hist = pd.DataFrame(dados_df_hist)
                st.write(f"**Total de votos: {total_votos_hist}**")
                for _, row_hist in df_hist.iterrows():
                    st.write(f"**{row_hist['opcao']}**: {row_hist['votos']} ({row_hist['percentual']:.1f}%)")
                    st.progress(int(row_hist["percentual"]))
        st.divider()
        if st.button("⬅️ Voltar à página principal", key="voltar_hist_main"):
            st.query_params.clear()
            st.rerun()
    else:
        st.error("Enquete não encontrada no histórico.")
        if st.button("⬅️ Voltar à página principal", key="voltar_hist_err"):
            st.query_params.clear()
            st.rerun()

def app_router():
    initialize_session_state()
    init_db() # init_db agora usa STRFTIME para default timestamp em historico_enquetes

    utc_tz = ZoneInfo("UTC")
    br_tz = ZoneInfo("America/Sao_Paulo")

    if 'user_voting_id' not in st.session_state:
        python_generated_id = str(uuid.uuid4())
        st.session_state.user_voting_id = python_generated_id
        
        js_ensure_cookie = f"""
            <script>
                function setCookie(name, value, days) {{
                    var expires = "";
                    if (days) {{
                        var date = new Date();
                        date.setTime(date.getTime() + (days*24*60*60*1000));
                        expires = "; expires=" + date.toUTCString();
                    }}
                    document.cookie = name + "=" + (value || "")  + expires + "; path=/; SameSite=Lax"; // Adicionado SameSite
                }}

                function getCookie(name) {{
                    var nameEQ = name + "=";
                    var ca = document.cookie.split(';');
                    for(var i=0;i < ca.length;i++) {{
                        var c = ca[i];
                        while (c.charAt(0)==' ') c = c.substring(1,c.length);
                        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length,c.length);
                    }}
                    return null;
                }}
                
                var idFromServer = "{python_generated_id}";
                // Sempre define/atualiza o cookie com o ID da sessão atual do Python.
                // Isso garante que o cookie do cliente reflita o ID da sessão mais recente,
                // mas não é usado pelo Python para restaurar um ID de uma sessão anterior
                // devido à dificuldade de ler o cookie de volta para o Python sem bibliotecas.
                setCookie("userVotingId_v2", idFromServer, 365);
            </script>
        """
        html(js_ensure_cookie, height=0)
        st.rerun() 
        return 
    
    page_param = st.query_params.get("page", None)
    enquete_id_param_list = st.query_params.get_all("enquete_id")
    enquete_id_param = enquete_id_param_list[0] if enquete_id_param_list else None

    if page_param == "historico_view":
        if enquete_id_param:
            try:
                enquete_id_hist = int(enquete_id_param)
                mostrar_enquete_historico(enquete_id_hist) 
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
            current_mode = st.session_state.get('modo')
            if not (current_mode == 'professor' or current_mode == 'login_professor'):
                st.query_params.clear() 
                st.session_state.modo = 'login_professor'
                st.session_state.pagina_professor = 'painel'
                st.rerun()
            elif current_mode == 'login_professor': 
                st.query_params.clear()
                st.rerun()

        if st.session_state.modo != 'professor':
            col_sb1, col_sb2 = st.columns([3,2])
            with col_sb1:
                if st.button("Aluno", key="sidebar_aluno_vfinal", use_container_width=True):
                    if st.session_state.modo != 'aluno':
                        st.query_params.clear() 
                        st.session_state.modo = 'aluno'
                        st.rerun()
            with col_sb2:
                if st.session_state.modo == 'aluno':
                    if st.button("🔄", key="sidebar_recarregar_vfinal", help="Recarregar enquete/resultados", use_container_width=True):
                        st.rerun()
        
        st.divider()
        st.title("Histórico")
        historico_enquetes = db_carregar_historico(limite=HISTORICO_LIMIT)
        if historico_enquetes:
            for item_hist in historico_enquetes:
                pergunta_curta = item_hist['pergunta'][:25] + "..." if len(item_hist['pergunta']) > 25 else item_hist['pergunta']
                ts_formatado = "Data inválida" 
                if item_hist['timestamp']:
                    timestamp_str = item_hist['timestamp']
                    try:
                        if timestamp_str.endswith('Z'):
                           utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        else:
                           naive_dt = datetime.fromisoformat(timestamp_str)
                           if naive_dt.tzinfo is None:
                               utc_dt = naive_dt.replace(tzinfo=utc_tz)
                           else:
                               utc_dt = naive_dt.astimezone(utc_tz)
                        
                        br_dt = utc_dt.astimezone(br_tz)
                        ts_formatado = br_dt.strftime('%d/%m %H:%M')
                    except ValueError: 
                        try: # Fallback para formato não-ISO comum
                            naive_dt = datetime.strptime(timestamp_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                            utc_dt = naive_dt.replace(tzinfo=utc_tz)
                            br_dt = utc_dt.astimezone(br_tz)
                            ts_formatado = br_dt.strftime('%d/%m %H:%M')
                        except ValueError:
                            ts_formatado = timestamp_str.split(' ')[0] # Último fallback

                link_html = f"<a href='?page=historico_view&enquete_id={item_hist['id']}' target='_self'>📊 {pergunta_curta} ({ts_formatado})</a>"
                st.markdown(f"<div class='sidebar-history-link'>{link_html}</div>", unsafe_allow_html=True)
        else:
            st.sidebar.caption("Nenhuma enquete no histórico")

    modo_atual = st.session_state.get('modo')
    if modo_atual == 'login_professor':
        mostrar_tela_login()
    elif modo_atual == 'professor':
        if st.session_state.pagina_professor == 'painel':
            mostrar_painel_professor()
        elif st.session_state.pagina_professor == 'alterar_senha':
            mostrar_tela_alterar_senha()
        else: 
            st.session_state.pagina_professor = 'painel'
            st.rerun()
    elif modo_atual == 'aluno':
        mostrar_tela_aluno()
    else: 
        st.session_state.modo = 'aluno'
        st.rerun()
    
    st.markdown("""<hr><div style="text-align:center; margin-top:40px; padding:10px; color:#000000; font-size:16px;"><h4>📊 Enquete App</h4>Sua enquete em tempo real<br>Por <strong>Ary Ribeiro:</strong> <a href="mailto:aryribeiro@gmail.com">aryribeiro@gmail.com</div>""", unsafe_allow_html=True)

if __name__ == "__main__":
    app_router()