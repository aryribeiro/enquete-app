# app.py
import streamlit as st
import pandas as pd
import time
from datetime import datetime
import hashlib
import json # Usado apenas para serializar/desserializar a lista de opções no DB
import sqlite3
import requests # Para buscar IP do aluno

# --- Configurações Globais e Constantes ---
DB_NAME = "enquete_app_vfinal.db" # Novo nome para evitar conflito com DBs antigos
MIN_OPTIONS = 2
MAX_OPTIONS = 10
DEFAULT_NUM_OPTIONS_ON_NEW = 2 # Default ao criar uma enquete do zero

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
    .stButton>button { width: 100%; } /* Para botões da sidebar preencherem a coluna */
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
    conn.execute("PRAGMA journal_mode=WAL;") # Habilita WAL mode para melhor concorrência
    conn.row_factory = sqlite3.Row # Permite acesso às colunas por nome
    return conn

def init_db():
    """
    Inicializa o banco de dados: cria tabelas se não existirem e
    insere configuração padrão (senha do admin).
    """
    admin_password_default = "admin123" # Senha padrão inicial
    admin_password_hash = hash_password(admin_password_default)
    
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tabela de Configuração Geral
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS configuracao (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('senha_professor', admin_password_hash))
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('enquete_ativa', '0')) # '0' para False, '1' para True
    cursor.execute("INSERT OR IGNORE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', str(datetime.now())))

    # Tabela para Definição da Enquete Ativa (apenas uma linha, id=1)
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

    # Tabela para Votos da Enquete Ativa
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_votos (
        opcao_indice INTEGER PRIMARY KEY,
        contagem INTEGER DEFAULT 0
    )
    """)

    # Tabela para IPs Votantes da Enquete Ativa
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enquete_ativa_ips_votantes (
        ip TEXT PRIMARY KEY
    )
    """)
    conn.commit()
    conn.close()

def db_carregar_config_valor(chave, default=None):
    """Carrega um valor específico da tabela de configuração."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT valor FROM configuracao WHERE chave = ?", (chave,))
    row = cursor.fetchone()
    conn.close()
    if row:
        if chave == 'enquete_ativa': # Tratar booleano especificamente
            return True if row['valor'] == '1' else False
        return row['valor']
    return default

def db_salvar_config_valor(chave, valor):
    """Salva um valor específico na tabela de configuração."""
    conn = get_db_connection()
    cursor = conn.cursor()
    valor_db = valor
    if chave == 'enquete_ativa': # Tratar booleano
        valor_db = '1' if valor else '0'
    
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", (chave, valor_db))
    cursor.execute("REPLACE INTO configuracao (chave, valor) VALUES (?, ?)", 
                   ('ultima_atualizacao_config', str(datetime.now())))
    conn.commit()
    conn.close()

def db_carregar_dados_enquete():
    """Carrega a pergunta e as opções da enquete ativa."""
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
            pass # Retorna default abaixo se JSON inválido
    return {"pergunta": "", "opcoes": [""] * DEFAULT_NUM_OPTIONS_ON_NEW}

def db_salvar_dados_enquete(pergunta, opcoes_lista):
    """Salva a pergunta e as opções da enquete ativa."""
    opcoes_json_str = json.dumps(opcoes_lista)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO enquete_ativa_definicao (id, pergunta, opcoes_json) VALUES (1, ?, ?)",
                   (pergunta, opcoes_json_str))
    conn.commit()
    conn.close()

def db_limpar_votos_e_ips(num_opcoes_enquete_atual):
    """Limpa os votos e IPs registrados, e reinicializa os contadores de voto."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM enquete_ativa_votos")
    cursor.execute("DELETE FROM enquete_ativa_ips_votantes")
    
    num_opcoes_valido = max(MIN_OPTIONS, min(num_opcoes_enquete_atual, MAX_OPTIONS))
    for i in range(num_opcoes_valido):
        cursor.execute("INSERT INTO enquete_ativa_votos (opcao_indice, contagem) VALUES (?, 0)", (i,))
    conn.commit()
    conn.close()

def db_carregar_resultados(num_opcoes_enquete_atual):
    """Carrega os resultados da votação (contagens e total)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT opcao_indice, contagem FROM enquete_ativa_votos ORDER BY opcao_indice ASC")
    votos_rows = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) as total_votos FROM enquete_ativa_ips_votantes")
    total_votos_row = cursor.fetchone()
    conn.close()

    total_votos = total_votos_row['total_votos'] if total_votos_row else 0
    votos_lista = [0] * num_opcoes_enquete_atual
    for row in votos_rows:
        if 0 <= row['opcao_indice'] < num_opcoes_enquete_atual:
            votos_lista[row['opcao_indice']] = row['contagem']
            
    return {"votos": votos_lista, "total_votos": total_votos}

def db_registrar_voto(opcao_indice, ip_votante):
    """Registra um voto. Retorna True se sucesso, False se IP já votou."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO enquete_ativa_ips_votantes (ip) VALUES (?)", (ip_votante,))
        cursor.execute("UPDATE enquete_ativa_votos SET contagem = contagem + 1 WHERE opcao_indice = ?", (opcao_indice,))
        conn.commit()
        return True
    except sqlite3.IntegrityError: # IP já existe (UNIQUE constraint falhou)
        return False 
    finally:
        conn.close()

def db_verificar_se_ip_votou(ip_votante):
    """Verifica se um IP já votou na enquete ativa."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM enquete_ativa_ips_votantes WHERE ip = ?", (ip_votante,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

# --- Gerenciamento de Estado da Sessão Streamlit ---
def initialize_session_state():
    """Inicializa as variáveis de estado da sessão do Streamlit se não existirem."""
    defaults = {
        'modo': 'aluno', 'client_ip': None, 'ip_fetch_error': False,
        'voto_registrado_nesta_sessao': False, 'pagina_professor': 'painel',
        'num_opcoes_edicao': DEFAULT_NUM_OPTIONS_ON_NEW,
        'first_load_ip_check_done': False, 'initial_rerun_for_ip_done': False
    }
    for key, value in defaults.items():
        if key not in st.session_state: st.session_state[key] = value
    
    # Resetar flags de busca de IP se estiver no modo aluno e IP não estiver definido
    if st.session_state.modo == 'aluno' and not st.session_state.client_ip and not st.session_state.ip_fetch_error:
        st.session_state.first_load_ip_check_done = False
        st.session_state.initial_rerun_for_ip_done = False

# --- Funções de Lógica da Aplicação e Renderização de UI ---
def fetch_client_ip_address():
    """Busca o IP do cliente silenciosamente e atualiza o estado da sessão."""
    if st.session_state.get('client_ip'): return st.session_state.client_ip
    if st.session_state.get('ip_fetch_error', False): return None
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=3)
        response.raise_for_status()
        ip_data = response.json()
        fetched_ip = ip_data.get("ip")
        if fetched_ip:
            st.session_state.client_ip = fetched_ip
            st.session_state.ip_fetch_error = False
            return fetched_ip
    except Exception:
        st.session_state.ip_fetch_error = True
    return None

def mostrar_tela_login():
    # ... (Implementação como na versão anterior, usando db_carregar_config_valor e hash_password)
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
    # Botões de Navegação do Painel
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🔐 Alterar Senha", key="painel_btn_alt_senha", use_container_width=True):
            st.session_state.pagina_professor = 'alterar_senha'; st.rerun(); return
    with col_nav2:
        if st.button("🚪 Logout", key="painel_btn_logout", use_container_width=True):
            st.session_state.modo = 'login_professor'; st.session_state.pagina_professor = 'painel'
            # Limpar flags de sessão do aluno/IP
            st.session_state.client_ip = None; st.session_state.ip_fetch_error = False
            st.session_state.voto_registrado_nesta_sessao = False
            st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
            st.rerun(); return
    st.divider()

    # Carregar dados atuais
    enquete_ativa_db = db_carregar_config_valor('enquete_ativa', False)
    dados_enquete_db = db_carregar_dados_enquete()
    
    # Input para número de opções
    opcoes_salvas = dados_enquete_db.get("opcoes", [])
    num_opcoes_atuais = len(opcoes_salvas) if opcoes_salvas else st.session_state.num_opcoes_edicao
    
    # Sincronizar st.session_state.num_opcoes_edicao com o que está no DB ou com o widget
    if 'num_opcoes_edicao_loaded' not in st.session_state or st.session_state.num_opcoes_edicao_loaded != num_opcoes_atuais:
        st.session_state.num_opcoes_edicao = max(MIN_OPTIONS, min(num_opcoes_atuais, MAX_OPTIONS))
        st.session_state.num_opcoes_edicao_loaded = num_opcoes_atuais

    num_opcoes_widget = st.number_input(
        "Número de Opções de Resposta:", min_value=MIN_OPTIONS, max_value=MAX_OPTIONS, 
        value=st.session_state.num_opcoes_edicao, step=1, key="prof_num_opcoes_selector",
        on_change=lambda: st.session_state.update({'num_opcoes_edicao': st.session_state.prof_num_opcoes_selector, 'num_opcoes_edicao_loaded': st.session_state.prof_num_opcoes_selector})
    )
    if st.session_state.num_opcoes_edicao != num_opcoes_widget: # Se mudou via widget
         st.session_state.num_opcoes_edicao = num_opcoes_widget
    
    # Formulário de Gerenciamento da Enquete
    st.subheader("Gerenciar Enquete")
    with st.form("painel_enquete_form_db_vfinal"):
        pergunta_form = st.text_input("Pergunta da Enquete", value=dados_enquete_db.get("pergunta", ""), key="painel_pergunta_db_vfinal")
        st.write(f"Opções de Resposta ({st.session_state.num_opcoes_edicao} opções):")
        
        opcoes_form_inputs = [""] * st.session_state.num_opcoes_edicao # Inicializa lista com tamanho correto
        for i in range(st.session_state.num_opcoes_edicao):
            val_opt = opcoes_salvas[i] if i < len(opcoes_salvas) else ""
            opcoes_form_inputs[i] = st.text_input(f"Opção {i+1}", value=val_opt, key=f"painel_opt_db_vfinal_{i}")
        
        submit_save_enquete = st.form_submit_button("Salvar e Ativar Enquete")
            
    if submit_save_enquete:
        opcoes_finais_para_salvar = [opcoes_form_inputs[i] for i in range(st.session_state.num_opcoes_edicao)]
        db_salvar_dados_enquete(pergunta_form, opcoes_finais_para_salvar)
        db_salvar_config_valor('enquete_ativa', True)
        db_limpar_votos_e_ips(len(opcoes_finais_para_salvar)) # Reseta votos para a nova enquete
        st.success("Enquete salva, ativada e votos resetados!"); st.rerun(); return
            
    if enquete_ativa_db:
        if st.button("Desativar Enquete", key="painel_desativar_db_vfinal"):
            db_salvar_config_valor('enquete_ativa', False)
            # Limpa votos da enquete que foi desativada
            num_opcoes_enq_desativada = len(db_carregar_dados_enquete().get("opcoes", []))
            db_limpar_votos_e_ips(max(MIN_OPTIONS, num_opcoes_enq_desativada))
            st.success("Enquete desativada e votos resetados!"); st.rerun(); return
    
    # Status e Resultados
    st.subheader("Status da Enquete")
    # Recarrega o status da enquete pois pode ter mudado
    enquete_ativa_status_display = db_carregar_config_valor('enquete_ativa', False) 
    if enquete_ativa_status_display: st.success("Enquete ATIVA")
    else: st.error("Enquete INATIVA")
    
    st.subheader("Resultados da Votação") # Chamado apenas UMA VEZ AQUI
    if enquete_ativa_status_display:
        dados_enquete_atuais_resultados = db_carregar_dados_enquete()
        num_opcoes_resultados = len(dados_enquete_atuais_resultados.get("opcoes",[]))
        resultados_db_display = db_carregar_resultados(max(MIN_OPTIONS, num_opcoes_resultados))
        mostrar_resultados(dados_enquete_atuais_resultados, resultados_db_display, refresh=True)
    else:
        st.info("A enquete está inativa. Ative-a para ver os resultados ou permitir novos votos.")

    # Refresh automático para o professor APENAS se a enquete estiver ativa.
    if enquete_ativa_status_display:
        time.sleep(3); st.rerun()

def mostrar_tela_alterar_senha():
    # ... (como na última versão, com keys atualizadas e return após rerun)
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
                st.session_state.pagina_professor = 'painel'; st.rerun(); return
    st.divider()
    if st.button("Voltar ao Painel", key="alt_voltar_vfinal"):
        st.session_state.pagina_professor = 'painel'; st.rerun(); return

def mostrar_tela_aluno():
    # ... (como na última versão que estava estável para o aluno, com ajustes para DB)
    config_enquete_ativa = db_carregar_config_valor('enquete_ativa', False)
    client_ip = st.session_state.get('client_ip')

    # Lógica de busca de IP (mais robusta para evitar reruns excessivos)
    if not client_ip and not st.session_state.get('ip_fetch_error', False):
        if not st.session_state.get('first_load_ip_check_done', False):
            client_ip = fetch_client_ip_address() # Nome da função de busca de IP
            st.session_state.first_load_ip_check_done = True
            # Só faz rerun se IP não foi obtido E não houve erro, e é a primeira tentativa de rerun
            if not client_ip and not st.session_state.get('ip_fetch_error', False) and \
               not st.session_state.get('initial_rerun_for_ip_done', False):
                st.session_state.initial_rerun_for_ip_done = True
                time.sleep(0.1); st.rerun() 
                # Não usar st.stop() aqui para permitir que o rodapé seja renderizado mesmo se o IP estiver pendente
    
    if not client_ip:
        if st.session_state.get('ip_fetch_error', False):
            st.title("📊 Enquete Indisponível"); st.error("Falha ao verificar IP. Recarregue (F5).")
        else:
            st.warning("Verificação de rede pendente. Use 'Recarregar' na barra lateral ou F5 se a enquete não aparecer.")
        return # Impede o resto se o IP não estiver pronto

    if not config_enquete_ativa:
        st.title("⌛ Aguardando Nova Enquete")
        st.info("Nenhuma enquete ativa no momento. Use o botão 'Recarregar' no Menu lateral para verificar novamente.")
        # O st.rerun automático foi removido daqui. O usuário usa o botão Recarregar.
        return

    # Se chegou aqui, enquete está ativa e temos IP
    dados_enquete_db = db_carregar_dados_enquete()
    opcoes_enquete_lista = dados_enquete_db.get("opcoes", [])
    num_opcoes_atual = len(opcoes_enquete_lista)
    resultados_db = db_carregar_resultados(max(MIN_OPTIONS, num_opcoes_atual)) # Garante min opções
    
    ja_votou_db = db_verificar_se_ip_votou(client_ip)
    st.session_state.voto_registrado_nesta_sessao = ja_votou_db

    st.title("📊 Participe da enquete")
    st.header(dados_enquete_db.get("pergunta","Enquete sem pergunta definida"))
    
    if st.session_state.get('voto_registrado_nesta_sessao', False):
        st.success(f"Seu voto (IP: {client_ip}) já foi registrado!"); 
        mostrar_resultados(dados_enquete_db, resultados_db, refresh=config_enquete_ativa)
    else:
        opcoes_validas_aluno = [opt for opt in opcoes_enquete_lista if opt and opt.strip()]
        if not dados_enquete_db.get("pergunta","").strip() or not opcoes_validas_aluno:
            st.warning("A enquete ainda não foi completamente configurada."); return

        key_radio_aluno = f"voto_radio_db_vfinal_{hashlib.md5(json.dumps(opcoes_validas_aluno).encode()).hexdigest()}"
        opcao_escolhida_aluno = st.radio("Escolha uma opção:", opcoes_validas_aluno, key=key_radio_aluno)
        
        if st.button("Votar", key="aluno_votar_db_vfinal"):
            ip_on_vote_db = fetch_client_ip_address() # Reconfirmar IP no momento do voto
            if not ip_on_vote_db: st.error("Falha ao verificar IP para voto. Recarregue."); return
            
            if db_verificar_se_ip_votou(ip_on_vote_db): # Checagem final
                st.warning(f"Voto já registrado para IP: {ip_on_vote_db}."); st.session_state.voto_registrado_nesta_sessao = True; st.rerun(); return
            
            if opcao_escolhida_aluno:
                try: 
                    indice_opcao_votada = opcoes_enquete_lista.index(opcao_escolhida_aluno)
                    if db_registrar_voto(indice_opcao_votada, ip_on_vote_db):
                        st.session_state.voto_registrado_nesta_sessao=True
                        st.success(f"Voto registrado (IP: {ip_on_vote_db})!"); time.sleep(1); st.rerun()
                    else: st.error("Erro: IP já votou (verificação falhou).") # Não deveria chegar aqui
                except ValueError: st.error("Opção inválida. Tente novamente.")
                except Exception as e: st.error(f"Erro ao votar: {e}")
            else: st.warning("Selecione uma opção.")

def mostrar_resultados(dados_enquete_param, resultados_param, refresh=False):
    # st.subheader("Resultados da Votação") # Agora chamado pelo chamador (mostrar_painel_professor)
    total_votos_param = resultados_param.get("total_votos", 0)
    if total_votos_param == 0: st.info("Ainda não há votos registrados."); return 
    
    opcoes_da_enquete_param = dados_enquete_param.get("opcoes", [])
    votos_registrados_param = resultados_param.get("votos", [])
    num_opcoes_atual_param = len(opcoes_da_enquete_param)

    # Ajusta a lista de votos para o número de opções atual, se necessário
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
            
    if refresh: time.sleep(2); st.rerun()

# --- Roteador Principal da Aplicação ---
def app_router():
    initialize_session_state()
    init_db() # Garante que o DB e tabelas existam

    with st.sidebar:
        st.title("Menu")
        
        # Botão Modo Professor (sempre visível, largura total da sidebar)
        if st.button("Professor", key="sidebar_prof_vfinal", use_container_width=True):
            current_mode = st.session_state.get('modo')
            if current_mode != 'login_professor': # Leva ao login se não estiver já lá
                st.session_state.modo = 'login_professor'
                st.session_state.pagina_professor = 'painel' 
                # Resetar flags de aluno se estava no modo aluno
                if current_mode == 'aluno':
                    st.session_state.client_ip = None; st.session_state.ip_fetch_error = False
                    st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                st.rerun()

        # Botões "Modo Aluno" e "Recarregar" lado a lado, se professor não estiver logado
        if st.session_state.modo != 'professor':
            col_sb1, col_sb2 = st.columns([3,2]) # Ajustar proporção se necessário
            with col_sb1:
                if st.button("Aluno", key="sidebar_aluno_vfinal", use_container_width=True):
                    if st.session_state.modo != 'aluno':
                        st.session_state.modo = 'aluno'
                        st.session_state.client_ip = None; st.session_state.ip_fetch_error = False
                        st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                        st.rerun()
            with col_sb2:
                if st.session_state.modo == 'aluno': 
                    if st.button("Recarregar", key="sidebar_recarregar_vfinal", help="Recarregar enquete/resultados", use_container_width=True):
                        st.session_state.client_ip = None; st.session_state.ip_fetch_error = False
                        st.session_state.first_load_ip_check_done = False; st.session_state.initial_rerun_for_ip_done = False
                        st.rerun()
    
    # Roteamento de tela principal
    modo_atual = st.session_state.get('modo')
    if modo_atual == 'login_professor': mostrar_tela_login(); st.stop()
    elif modo_atual == 'professor':
        if st.session_state.pagina_professor == 'painel': mostrar_painel_professor()
        elif st.session_state.pagina_professor == 'alterar_senha': mostrar_tela_alterar_senha()
        else: st.session_state.pagina_professor = 'painel'; st.rerun()
        st.stop() # Para garantir que só a tela do professor execute
    elif modo_atual == 'aluno':
        mostrar_tela_aluno()
        # st.stop() aqui pode ser problemático se mostrar_tela_aluno precisar de um rerun interno para IP
        # A lógica interna de return em mostrar_tela_aluno deve ser suficiente.
    else: # Estado inválido
        st.session_state.modo = 'aluno'; st.rerun() 
    
    # Rodapé
    st.markdown("""<hr><div style="text-align:center; margin-top:40px; padding:10px; color:#000000; font-size:16px;"><h4>📊 Enquete App</h4>Sua enquete em tempo real<br>Por <strong>Ary Ribeiro:</strong> <a href="mailto:aryribeiro@gmail.com">aryribeiro@gmail.com</div>""", unsafe_allow_html=True)

if __name__ == "__main__":
    app_router()