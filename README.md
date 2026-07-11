Obs.: caso o app esteja no modo "sleeping" (dormindo) ao entrar, basta clicar no botão que estará disponível e aguardar, para ativar o mesmo. 
![print](https://github.com/user-attachments/assets/9fe30760-1ecf-48ee-83ac-f7030c05cc39)

# 📊Enquete App | Sua Enquete em Tempo Real

O Enquete App é uma aplicação web construída com Streamlit e Python que permite a criação de enquetes em tempo real. É ideal para salas de aula, apresentações ou qualquer situação onde um feedback rápido do público é necessário.

## Funcionalidades Principais

* **Dois Modos de Usuário**:
    * **Professor**: Controla a enquete.
    * **Aluno**: Participa da enquete.
* **Painel do Professor**:
    * Login com senha (hash PBKDF2-HMAC-SHA256, 100.000 iterações, com salt configurável via variável de ambiente `PASSWORD_SALT`).
    * Criação e edição de enquetes com pergunta e um número flexível de opções de resposta (2 a 10).
    * Ao salvar e ativar uma nova enquete, os votos anteriores são resetados e a enquete anterior (se ativa) é arquivada no histórico.
    * Ao desativar uma enquete, os resultados são arquivados no histórico e os votos resetados.
    * Visualização dos resultados da votação em tempo real (auto-refresh a cada 5 segundos).
    * Opção para alterar a senha do professor.
    * Botão de Logout.
* **Interface do Aluno**:
    * Visualização da enquete ativa, com opções **sem pré-seleção** (nenhuma alternativa vem marcada).
    * **Voto único por IP público**: o IP do aluno é obtido no servidor via header `X-Forwarded-For` do proxy (não é o IP do servidor Streamlit). F5, abrir outra aba ou até outro navegador no mesmo dispositivo/rede **não** permitem votar de novo — o aluno só volta a votar quando o professor ativa uma nova enquete.
    * Após votar, o aluno acompanha os resultados em tempo real: as barras de progresso se movem automaticamente (auto-refresh a cada 5 segundos).
    * Tela de "Aguardando Nova Enquete" com auto-refresh — quando o professor ativa uma enquete, ela aparece sozinha na tela do aluno.
    * Botão 🔄 na barra lateral para atualização manual, se desejado.
* **Histórico de Enquetes**:
    * As últimas 5 enquetes encerradas ficam arquivadas (pergunta, opções, votos e total).
    * Acessíveis por links na barra lateral, com data/hora no fuso de Brasília.
* **Persistência de Dados**:
    * Banco de dados **SQLite (`enquete_app_vfinal_cookie.db`)** em modo WAL, armazenando:
        * Configurações da aplicação (senha do professor, status da enquete).
        * Definição da enquete ativa (pergunta e opções).
        * Contagem de votos para cada opção.
        * IPs dos participantes que já votaram na enquete ativa.
        * Histórico das últimas enquetes encerradas.
    * **Atenção (Streamlit Community Cloud)**: o disco é efêmero — o banco (incluindo histórico e senha alterada) é zerado em reboot/redeploy/sleep da aplicação.
* **Interface Customizada**:
    * Layout limpo e focado, com elementos padrão do Streamlit ocultados (menu, header, footer) para uma experiência mais imersiva.

## Tecnologias Utilizadas

* **Python 3**
* **Streamlit 1.36.0** (versão pinada): interface web interativa.
* **SQLite**: armazenamento de dados persistente (WAL, busy_timeout, retry em falhas de acesso).
* **Pandas**: manipulação de dados.

## Estrutura do Projeto
├── app.py                          # Código principal da aplicação Streamlit
├── requirements.txt                # Dependências (streamlit==1.36.0, pandas)
└── enquete_app_vfinal_cookie.db    # Banco SQLite (criado na primeira execução)

## Pré-requisitos

* Python 3.9 ou superior.
* `pip` (gerenciador de pacotes Python).
* No **Windows**, instale também o pacote `tzdata` (`pip install tzdata`) — necessário para o fuso horário de Brasília. No Linux/Streamlit Cloud não é preciso.

## Instalação e Execução

1.  **Clone o repositório:**
    ```bash
    git clone https://github.com/aryribeiro/enquete-app.git
    cd enquete-app
    ```

2.  **Crie e ative um ambiente virtual (recomendado):**
    ```bash
    python -m venv venv
    # No Windows:
    # venv\Scripts\activate
    # No macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Instale as dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Execute a aplicação Streamlit:**
    ```bash
    streamlit run app.py
    ```
    A aplicação será aberta automaticamente no seu navegador web.

## Configuração Inicial

* Na primeira execução, o banco de dados `enquete_app_vfinal_cookie.db` será criado.
* A senha padrão do professor é `admin123`. É altamente recomendável alterá-la através do painel do professor após o primeiro login.
* Opcional: defina a variável de ambiente `PASSWORD_SALT` (ou secret no Streamlit Cloud) para usar um salt próprio no hash de senha.

## Como Usar

1.  **Professor**:
    * Acesse o aplicativo.
    * Abra o menu lateral e clique em "Professor".
    * Faça login com a senha (padrão: `admin123`).
    * No painel do professor:
        * Defina o número de opções de resposta desejado.
        * Digite a pergunta da enquete e as opções de resposta.
        * Clique em "Salvar e Ativar Enquete". Os votos são resetados e todos os alunos podem votar.
        * Monitore os resultados em tempo real.
        * Para encerrar a votação, clique em "Desativar Enquete" — os resultados vão para o histórico.
        * Use "Alterar Senha" para definir uma nova senha e "Logout" para sair.

2.  **Aluno**:
    * Acesse o aplicativo. Se não houver enquete ativa, a tela "Aguardando Nova Enquete" atualiza sozinha até uma enquete ser ativada.
    * Quando a enquete aparecer, selecione uma opção (nenhuma vem marcada) e clique em "Votar".
    * Após votar, os resultados são exibidos e as barras se atualizam automaticamente.
    * Recarregar a página ou abrir outro navegador não permite votar novamente na mesma enquete.

## Limitações Conhecidas

* **Controle por IP público**: alunos que compartilham o mesmo IP de saída (ex.: todos no mesmo Wi-Fi de escola/empresa atrás de NAT) são vistos como um único votante — apenas o primeiro conseguirá votar. O cenário ideal é cada aluno usar sua própria conexão (ex.: 4G/5G).
* **Disco efêmero no Streamlit Community Cloud**: histórico e senha alterada são perdidos quando a aplicação reinicia ou hiberna.

## Possíveis Melhorias Futuras

* Voto único combinando IP + identificador de dispositivo (para turmas em Wi-Fi compartilhado).
* Suporte para múltiplas enquetes salvas além do limite de 5 no histórico.
* Exportação de resultados da enquete (ex: para CSV).
* Autenticação de alunos (se necessário para cenários mais controlados).
* Banco de dados externo (ex: Turso/PostgreSQL) para persistência real no Streamlit Cloud.

## Autor

* **Ary Ribeiro**
* Contato: [aryribeiro@gmail.com](mailto:aryribeiro@gmail.com)
