# app.py
import streamlit as st
import pandas as pd
import time
from datetime import datetime
import hashlib
import json # Usado apenas para serializar/desserializar a lista de opções no DB
import sqlite3
import requests # Para buscar IP do aluno (server-side)
from streamlit.components.v1 import html as st_html # Para o IP via JS

# --- Configurações Globais e Constantes ---
DB_NAME = "enquete_app_vfinal_multi_user.db" # Novo nome para refletir a mudança
MIN_OPTIONS = 2
MAX_OPTIONS = 10
DEFAULT_NUM_OPTIONS_ON_NEW = 2 # Default ao criar uma enquete do zero
HISTORICO_LIMIT = 5

# --- CSS Styling ---
st.set_page_config(
    page_title="Enquete App | Sua enquete em tempo real",
    page_icon="📊",
    layout="centered",
)
# Estilo CSS (mantido como no original, mas pode precisar de ajustes para a nova view)
st.markdown("""
<style>
    .main { background-color: #ffffff; color: #333333; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    header, footer, #MainMenu { display: none !important; }
    div[data-testid="stAppViewBlockContainer"], div[data-testid="stVerticalBlock"] {
        padding-top: 0 !important; padding-bottom: 0 !important; gap: 0 !important;
    }
    .element-container { margin-top: 0 !important; margin-bottom: 0 !important; }
    .stButton>button { width: 100%; } /* Para botões da sidebar preencherem a coluna */
    /* Estilo para links do histórico na sidebar */
    .sidebar-history-link a {
        font-size: 0.9em;
        text-decoration: none;
        display: block; /* Faz o link ocupar a largura e permite padding */
        padding: 4px 0px; /* Ajuste o padding conforme necessário */
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .sidebar-history-link a:hover {
        text-decoration: underline;
    }
    #client-ip-js { font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- Funções Utilitárias ---
def hash_password(password):
    """Gera um hash SHA256 para a senha fornecida."""
    return hashlib.sha256(password.encode()).hexdigest()

# --- Funções de Banco de Dados (SQLite) ---
def get_db_connection():
    """Estabelece e retorna uma conexão com o banco de dados SQLite."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Inicializa o banco de dados: cria tabelas se não existirem e
    insere configuração padrão (senha do admin).
    """
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
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', str(datetime.now())))

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

    # A tabela enquete_ativa_ips_votantes foi REMOVIDA para permitir múltiplos votos.
    # A restrição de voto único por IP foi eliminada do banco de dados.
    # A restrição de voto agora é por SESSÃO do Streamlit.

    # Nova tabela para o Histórico de Enquetes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historico_enquetes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        pergunta TEXT NOT NULL,
        opcoes_json TEXT NOT NULL,
        votos_json TEXT NOT NULL,
        total_votos INTEGER DEFAULT 0
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historico_timestamp ON historico_enquetes (timestamp DESC);")

    conn.commit()
    conn.close()

# --- Funções de DB para Histórico ---
def db_adicionar_ao_historico(pergunta, opcoes_lista, votos_lista, total_votos_final):
    if not pergunta or not opcoes_lista: # Não salva histórico se dados essenciais estiverem faltando
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

# --- Demais funções de DB (db_carregar_config_valor, db_salvar_config_valor, etc.) ---
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
    
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", (chave, valor_db))
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', str(datetime.now())))
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

def db_limpar_votos(num_opcoes_enquete_atual): # Renomeado de db_limpar_votos_e_ips
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM enquete_ativa_votos")
    # Não há mais tabela enquete_ativa_ips_votantes para limpar
    
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
    
    # Calcula o total de votos somando as contagens de cada opção
    cursor.execute("SELECT SUM(contagem) as total_votos FROM enquete_ativa_votos")
    total_votos_row = cursor.fetchone()
    conn.close()

    total_votos = total_votos_row['total_votos'] if total_votos_row and total_votos_row['total_votos'] is not None else 0
    votos_lista = [0] * num_opcoes_enquete_atual
    for row in votos_rows:
        if 0 <= row['opcao_indice'] < num_opcoes_enquete_atual:
            votos_lista[row['opcao_indice']] = row['contagem']
            
    return {"votos": votos_lista, "total_votos": total_votos}

def db_registrar_voto(opcao_indice): # Removido ip_votante como parâmetro de restrição
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Não há mais inserção em enquete_ativa_ips_votantes
        cursor.execute("UPDATE enquete_ativa_votos SET contagem = contagem + 1 WHERE opcao_indice = ?", (opcao_indice,))
        conn.commit()
        return True
    except sqlite3.Error as e: # Erro genérico de banco de dados
        st.error(f"Erro de banco de dados ao registrar voto: {e}")
        return False 
    finally:
        conn.close()

# A função db_verificar_se_ip_votou foi REMOVIDA. A lógica de "já votou" agora é por sessão.

# --- Gerenciamento de Estado da Sessão Streamlit ---
def initialize_session_state():
    defaults = {
        'modo': 'aluno', 
        'client_ip_server_side': None, # IP detectado pelo servidor (requests)
        'ip_fetch_error': False,
        'voto_registrado_nesta_sessao': False, 
        'pagina_professor': 'painel',
        'num_opcoes_edicao': DEFAULT_NUM_OPTIONS_ON_NEW,
        'first_load_ip_check_done': False, 
        'initial_rerun_for_ip_done': False
    }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value
    
    if st.session_state.modo == 'aluno' and not st.session_state.client_ip_server_side and not st.session_state.ip_fetch_error:
        st.session_state.first_load_ip_check_done = False
        st.session_state.initial_rerun_for_ip_done = False

# --- Funções de Lógica da Aplicação e Renderização de UI ---
def fetch_client_ip_address_server_side(): # Renomeado para clareza
    """Busca o IP do cliente da perspectiva do servidor."""
    if st.session_state.get('client_ip_server_side'): return st.session_state.client_ip_server_side
    if st.session_state.get('ip_fetch_error', False): return None
    try:
        # Este IP é como o servidor Streamlit vê o cliente.
        # Se o app estiver atrás de um proxy reverso, pode ser o IP do proxy.
        # Se o app estiver rodando localmente, pode ser localhost ou IP da rede interna.
        response = requests.get("https://api.ipify.org?format=json", timeout=3)
        response.raise_for_status()
        ip_data = response.json()
        fetched_ip = ip_data.get("ip")
        if fetched_ip:
            st.session_state.client_ip_server_side = fetched_ip
            st.session_state.ip_fetch_error = False
            return fetched_ip
    except Exception:
        st.session_state.ip_fetch_error = True
    return None

def get_js_ip_fetcher_html():
    """Retorna o HTML e JavaScript para buscar o IP no lado do cliente e exibi-lo."""
    # Técnica similar ao list.py para buscar e exibir o IP via JavaScript
    # O IP aqui é o IP público real do cliente, detectado pelo navegador dele.
    ip_html_code = """
    <script>
        async function fetchAndDisplayUserIPForEnquete() {
            const ipElement = document.getElementById('client-ip-js');
            if (!ipElement) return; // Sai se o elemento não existir na página atual

            try {
                let response = await fetch('https://ipinfo.io/json', {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' },
                    cache: 'no-cache' // Tenta evitar cache
                });
                
                if (!response.ok) {
                    // Fallback para outro serviço se o primeiro falhar
                    response = await fetch('https://api.ipify.org?format=json', {
                        method: 'GET',
                        headers: { 'Accept': 'application/json' },
                        cache: 'no-cache'
                    });
                }

                if (!response.ok) {
                    throw new Error('Serviços de IP falharam');
                }

                const data = await response.json();
                const ip = data.ip || 'Não disponível';
                ipElement.textContent = ip;
            } catch (error) {
                console.error('Erro ao buscar IP via JS:', error);
                ipElement.textContent = 'Falha ao obter';
            }
        }
        // Garante que a função rode após o DOM estar pronto e o elemento existir
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fetchAndDisplayUserIPForEnquete);
        } else {
            fetchAndDisplayUserIPForEnquete();
        }
    </script>
    """
    return ip_html_code

def mostrar_tela_login():
    st.title("🔐 Login do Professor")
    senha_digitada = st.text_input("Senha", type="password", key="login_senha_vfinal")
    if st.button("Entrar", key="login_entrar_vfinal"):
        senha_hash_db = db_carregar_config_valor("senha_professor")
        if senha_hash_db and hash_password(senha_digitada) == senha_hash_db:
            st.session_state.modo = 'professor'; st.session_state.pagina_professor = 'painel' 
            st.success("Login realizado com sucesso!")
            st.rerun()
        else: st.error("Senha incorreta!")

def mostrar_painel_professor():
    st.title("🖥️​ Painel do Professor")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🔐 Alterar Senha", key="painel_btn_alt_senha", use_container_width=True):
            st.session_state.pagina_professor = 'alterar_senha'; st.rerun(); return
    with col_nav2:
        if st.button("🚪 Logout", key="painel_btn_logout", use_container_width=True):
            st.session_state.modo = 'login_professor'; st.session_state.pagina_professor = 'painel'
            st.session_state.client_ip_server_side = None; st.session_state.ip_fetch_error = False
            st.session_state.voto_registrado_nesta_sessao = False # Reset ao sair
            st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
            st.rerun(); return
    st.divider()

    enquete_ativa_db = db_carregar_config_valor('enquete_ativa', False)
    dados_enquete_db = db_carregar_dados_enquete()
    
    opcoes_salvas = dados_enquete_db.get("opcoes", [])
    num_opcoes_atuais = len(opcoes_salvas) if opcoes_salvas else st.session_state.num_opcoes_edicao
    
    if 'num_opcoes_edicao_loaded' not in st.session_state or st.session_state.num_opcoes_edicao_loaded != num_opcoes_atuais:
        st.session_state.num_opcoes_edicao = max(MIN_OPTIONS, min(num_opcoes_atuais, MAX_OPTIONS))
        st.session_state.num_opcoes_edicao_loaded = num_opcoes_atuais

    num_opcoes_widget = st.number_input(
        "Número de Opções de Resposta:", min_value=MIN_OPTIONS, max_value=MAX_OPTIONS, 
        value=st.session_state.num_opcoes_edicao, step=1, key="prof_num_opcoes_selector",
        on_change=lambda: st.session_state.update({'num_opcoes_edicao': st.session_state.prof_num_opcoes_selector, 'num_opcoes_edicao_loaded': st.session_state.prof_num_opcoes_selector})
    )
    if st.session_state.num_opcoes_edicao != num_opcoes_widget:
         st.session_state.num_opcoes_edicao = num_opcoes_widget
    
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
            db_limpar_votos(len(opcoes_finais_para_salvar)) # Passar o número de opções para inicializar corretamente
            st.session_state.voto_registrado_nesta_sessao = False # Permite novo voto na nova enquete
            st.success("Enquete salva, ativada e votos resetados!"); st.rerun()
            
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
            db_limpar_votos(max(MIN_OPTIONS, num_opcoes_enq_desativada_calc)) # Limpa os votos da enquete desativada
            st.session_state.voto_registrado_nesta_sessao = False # Reset
            st.success("Enquete desativada, resultados arquivados e votos resetados!"); st.rerun()
    
    st.subheader("Status da Enquete")
    enquete_ativa_status_display = db_carregar_config_valor('enquete_ativa', False) 
    if enquete_ativa_status_display: st.success("Enquete ATIVA")
    else: st.error("Enquete INATIVA")
    
    st.subheader("Resultados da Votação")
    if enquete_ativa_status_display:
        dados_enquete_atuais_resultados = db_carregar_dados_enquete()
        num_opcoes_resultados = len(dados_enquete_atuais_resultados.get("opcoes",[]))
        if num_opcoes_resultados > 0 : 
            resultados_db_display = db_carregar_resultados(num_opcoes_resultados)
            mostrar_resultados(dados_enquete_atuais_resultados, resultados_db_display, refresh=True)
        else:
            st.info("A enquete ativa não possui opções configuradas.")
    else:
        st.info("A enquete está inativa. Ative-a para ver os resultados ou permitir novos votos.")

    if enquete_ativa_status_display:
        time.sleep(3); st.rerun()

def mostrar_tela_alterar_senha():
    st.title("🔑 Alterar Senha do Professor")
    with st.form("alt_senha_frm_vfinal"):
        nova_senha = st.text_input("Nova Senha", type="password", key="alt_nova_senha_vfinal")
        confirmar = st.text_input("Confirmar Nova Senha", type="password", key="alt_confirma_vfinal")
        submit = st.form_submit_button("Confirmar Alteração")
        if submit:
            if not nova_senha or not confirmar: st.error("Campos não podem ser vazios.")
            elif nova_senha != confirmar: st.error("Senhas não coincidem.")
            elif len(nova_senha) < 6: st.error("Senha curta (mínimo 6 caracteres).")
            else:
                db_salvar_config_valor('senha_professor', hash_password(nova_senha))
                st.success("Senha alterada! Retornando ao painel..."); time.sleep(1.5)
                st.session_state.pagina_professor = 'painel'; st.rerun()
    st.divider()
    if st.button("Voltar ao Painel", key="alt_voltar_vfinal"):
        st.session_state.pagina_professor = 'painel'; st.rerun()

def mostrar_tela_aluno():
    st_html(get_js_ip_fetcher_html(), height=0) # Adiciona o JS para buscar IP no cliente

    config_enquete_ativa = db_carregar_config_valor('enquete_ativa', False)
    
    # Tentativa de obter IP server-side (para log ou info, não para restrição de voto)
    # O client_ip_server_side é o IP que o servidor Streamlit vê.
    client_ip_server = st.session_state.get('client_ip_server_side')
    if not client_ip_server and not st.session_state.get('ip_fetch_error', False):
        if not st.session_state.get('first_load_ip_check_done', False):
            client_ip_server = fetch_client_ip_address_server_side()
            st.session_state.first_load_ip_check_done = True
            if not client_ip_server and not st.session_state.get('ip_fetch_error', False) and \
               not st.session_state.get('initial_rerun_for_ip_done', False):
                st.session_state.initial_rerun_for_ip_done = True
                time.sleep(0.1); st.rerun() 
    
    st.markdown("IP (detectado pelo servidor): " + (client_ip_server if client_ip_server else "Não detectado"))
    st.markdown("IP (detectado pelo navegador): <span id='client-ip-js'>Carregando...</span>", unsafe_allow_html=True)


    if not config_enquete_ativa:
        st.title("⌛ Aguardando Nova Enquete")
        st.info("Nenhuma enquete ativa no momento. Use o botão 'Recarregar' no Menu lateral para verificar novamente.")
        # Resetar o estado de voto da sessão se não há enquete ativa,
        # para permitir votar se uma nova enquete for ativada.
        if st.session_state.voto_registrado_nesta_sessao:
            st.session_state.voto_registrado_nesta_sessao = False
        return

    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_enquete_lista = dados_enquete_db.get("opcoes", [])
    num_opcoes_atual = len(opcoes_enquete_lista)

    if not dados_enquete_db.get("pergunta","").strip() or num_opcoes_atual < MIN_OPTIONS :
         st.title("⌛ Enquete em Configuração")
         st.info("A enquete atual ainda não está pronta. Por favor, aguarde.")
         return 
    
    resultados_db = db_carregar_resultados(num_opcoes_atual)
    
    # A verificação de "já votou" agora é baseada na sessão do Streamlit
    # st.session_state.voto_registrado_nesta_sessao é setado para True após um voto.
    # Ele é resetado para False quando uma nova enquete é ativada pelo professor,
    # ou quando o usuário faz logout/login, ou se a enquete for desativada.

    st.title("📊 Participe da enquete")
    st.header(dados_enquete_db.get("pergunta","Enquete sem pergunta definida"))
    
    if st.session_state.get('voto_registrado_nesta_sessao', False):
        st.success("Seu voto nesta sessão já foi registrado!"); 
        mostrar_resultados(dados_enquete_db, resultados_db, refresh=config_enquete_ativa)
    else:
        opcoes_validas_aluno = [opt for opt in opcoes_enquete_lista if opt and opt.strip()]
        if not opcoes_validas_aluno:
            st.warning("A enquete não possui opções válidas no momento."); return

        key_radio_aluno = f"voto_radio_db_vfinal_{hashlib.md5(json.dumps(opcoes_validas_aluno).encode()).hexdigest()}"
        opcao_escolhida_aluno = st.radio("Escolha uma opção:", opcoes_validas_aluno, key=key_radio_aluno)
        
        if st.button("Votar", key="aluno_votar_db_vfinal"):
            # Não há mais verificação de IP no banco de dados antes de registrar o voto.
            # A única restrição é o st.session_state.voto_registrado_nesta_sessao.
            
            if opcao_escolhida_aluno:
                try: 
                    indice_opcao_votada = opcoes_enquete_lista.index(opcao_escolhida_aluno)
                    if db_registrar_voto(indice_opcao_votada): # Não passa mais IP
                        st.session_state.voto_registrado_nesta_sessao = True # Marca que votou nesta sessão
                        st.success("Voto registrado!"); time.sleep(1); st.rerun()
                    else: st.error("Erro ao registrar voto no banco de dados.") # Erro genérico do DB
                except ValueError: st.error("Opção inválida. Tente novamente.")
                except Exception as e: st.error(f"Erro ao votar: {e}")
            else: st.warning("Selecione uma opção.")

def mostrar_resultados(dados_enquete_param, resultados_param, refresh=False):
    total_votos_param = resultados_param.get("total_votos", 0)
    opcoes_da_enquete_param = dados_enquete_param.get("opcoes", [])
    
    if not opcoes_da_enquete_param:
        st.info("Não há opções definidas para esta enquete.")
        return

    if total_votos_param == 0: st.info("Ainda não há votos registrados."); return 
    
    votos_registrados_param = resultados_param.get("votos", [])
    num_opcoes_atual_param = len(opcoes_da_enquete_param)

    if len(votos_registrados_param) != num_opcoes_atual_param:
        votos_ajustados = [0] * num_opcoes_atual_param
        for i in range(min(len(votos_registrados_param), num_opcoes_atual_param)):
            votos_ajustados[i] = votos_registrados_param[i]
        votos_registrados_param = votos_ajustados
    
    dados_para_df_param = []
    for i, opt_txt_param in enumerate(opcoes_da_enquete_param):
        if opt_txt_param and opt_txt_param.strip():
            v_count_param = votos_registrados_param[i] if i < len(votos_registrados_param) else 0
            perc_param = (v_count_param/total_votos_param)*100 if total_votos_param > 0 else 0
            dados_para_df_param.append({"opcao":opt_txt_param, "votos":v_count_param, "percentual":perc_param})
    
    if not dados_para_df_param: st.info("Sem dados de votação válidos para exibir."); return
    
    df_param = pd.DataFrame(dados_para_df_param)
    st.write(f"**Total de votos: {total_votos_param}**")
    for _, row_param in df_param.iterrows():
        st.write(f"**{row_param['opcao']}**: {row_param['votos']} ({row_param['percentual']:.1f}%)"); st.progress(int(row_param["percentual"]))
            
    if refresh and st.session_state.modo == 'professor': 
        time.sleep(2); st.rerun()
    elif refresh and st.session_state.modo == 'aluno' and db_carregar_config_valor('enquete_ativa', False): 
        time.sleep(5); st.rerun()


# --- Nova Função para Mostrar Enquete do Histórico ---
def mostrar_enquete_historico(id_historico):
    dados_enquete = db_carregar_enquete_historico_por_id(id_historico)
    if dados_enquete:
        st.title(f"📜 Histórico da Enquete")
        st.subheader(f"Pergunta: {dados_enquete['pergunta']}")
        try:
            ts_obj = datetime.fromisoformat(dados_enquete['timestamp'])
            st.caption(f"Realizada em: {ts_obj.strftime('%d/%m/%Y %H:%M:%S')}")
        except ValueError: 
            st.caption(f"Realizada em: {dados_enquete['timestamp'].split('.')[0]}") 
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
            if len(votos_hist) != num_opcoes_hist: 
                votos_ajustados = [0] * num_opcoes_hist
                for i in range(min(len(votos_hist), num_opcoes_hist)):
                    votos_ajustados[i] = votos_hist[i]
                votos_hist = votos_ajustados
            
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

# --- Roteador Principal da Aplicação ---
def app_router():
    initialize_session_state()
    init_db()
    
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
                    st.query_params.clear(); st.rerun()
                return
        else:
            st.warning("ID da enquete do histórico não fornecido.")
            if st.button("⬅️ Voltar"):
                st.query_params.clear(); st.rerun()
            return

    # Barra Lateral
    with st.sidebar:
        st.title("Menu")
        
        if st.button("Professor", key="sidebar_prof_vfinal", use_container_width=True):
            current_mode = st.session_state.get('modo')
            if not (current_mode == 'professor' or current_mode == 'login_professor'):
                st.query_params.clear() 
                st.session_state.modo = 'login_professor'
                st.session_state.pagina_professor = 'painel' 
                if current_mode == 'aluno': # Resetar ao mudar de aluno para professor
                    st.session_state.client_ip_server_side = None; st.session_state.ip_fetch_error = False
                    st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                    st.session_state.voto_registrado_nesta_sessao = False 
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
                        st.session_state.client_ip_server_side = None; st.session_state.ip_fetch_error = False
                        st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                        # st.session_state.voto_registrado_nesta_sessao = False # Não resetar aqui, pois pode haver enquete ativa
                        st.rerun()
            with col_sb2:
                if st.session_state.modo == 'aluno': 
                    if st.button("Recarregar", key="sidebar_recarregar_vfinal", help="Recarregar enquete/resultados", use_container_width=True):
                        # Mantém o estado de voto da sessão, mas reseta a busca de IP
                        st.session_state.client_ip_server_side = None; st.session_state.ip_fetch_error = False
                        st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                        st.rerun()
        
        st.divider() 
        st.title("Histórico")
        historico_enquetes = db_carregar_historico(limite=HISTORICO_LIMIT)
        if historico_enquetes:
            for item_hist in historico_enquetes:
                pergunta_curta = item_hist['pergunta'][:25] + "..." if len(item_hist['pergunta']) > 25 else item_hist['pergunta']
                try:
                    ts_obj = datetime.fromisoformat(item_hist['timestamp'])
                    ts_formatado = ts_obj.strftime('%d/%m %H:%M')
                except ValueError: 
                    try: 
                        ts_obj = datetime.strptime(item_hist['timestamp'].split('.')[0], '%Y-%m-%d %H:%M:%S')
                        ts_formatado = ts_obj.strftime('%d/%m %H:%M')
                    except ValueError: 
                        ts_formatado = item_hist['timestamp'].split(' ')[0] 

                link_html = f"<a href='?page=historico_view&enquete_id={item_hist['id']}' target='_self'>📊 {pergunta_curta} ({ts_formatado})</a>"
                st.markdown(f"<div class='sidebar-history-link'>{link_html}</div>", unsafe_allow_html=True)
        else:
            st.sidebar.caption("Nenhuma enquete no histórico")
    
    # Roteamento de tela principal
    modo_atual = st.session_state.get('modo')
    if modo_atual == 'login_professor': mostrar_tela_login()
    elif modo_atual == 'professor':
        if st.session_state.pagina_professor == 'painel': mostrar_painel_professor()
        elif st.session_state.pagina_professor == 'alterar_senha': mostrar_tela_alterar_senha()
        else: st.session_state.pagina_professor = 'painel'; st.rerun()
    elif modo_atual == 'aluno':
        mostrar_tela_aluno()
    else: 
        st.session_state.modo = 'aluno'; st.rerun() 
    
    st.markdown("""<hr><div style="text-align:center; margin-top:40px; padding:10px; color:#000000; font-size:16px;"><h4>📊 Enquete App</h4>Sua enquete em tempo real<br>Por <strong>Ary Ribeiro:</strong> <a href="mailto:aryribeiro@gmail.com">aryribeiro@gmail.com</div>""", unsafe_allow_html=True)

if __name__ == "__main__":
    app_router()