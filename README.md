# Enquete em Tempo Real (Streamlit)

Um aplicativo web para criar e gerenciar enquetes em tempo real para uso em sala de aula. Ideal para professores que desejam interagir com seus alunos e obter feedback instantâneo durante as aulas.

## 🌟 Funcionalidades

- **Modo Professor**: Interface protegida por senha para criar e gerenciar enquetes
- **Modo Aluno**: Interface simplificada para participar das enquetes
- **Enquetes em Tempo Real**: Atualizações automáticas na tela dos alunos quando uma nova enquete é criada
- **Visualização dos Resultados**: Apresentação dos resultados com barras horizontais e percentuais
- **Persistência de Dados**: Os dados são salvos localmente e mantidos entre sessões

## 🔧 Instalação

1. Clone este repositório ou baixe os arquivos
2. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
3. Execute o aplicativo:
   ```
   streamlit run app.py
   ```

## 📋 Como Usar

### Modo Professor

1. Acesse o modo professor através da barra lateral
2. Faça login com a senha (padrão: `admin123`)
3. Crie uma nova enquete:
   - Digite a pergunta
   - Adicione até 5 opções de resposta
   - Clique em "Salvar e Ativar Enquete"
4. Acompanhe os resultados em tempo real
5. Use o botão "Desativar Enquete" quando desejar encerrar a votação
6. Use o botão "Resetar Votos" para limpar os resultados anteriores

### Modo Aluno

1. Aguarde o professor criar e ativar uma enquete
2. Quando a enquete estiver ativa, selecione uma opção de resposta
3. Clique em "Votar" para registrar seu voto
4. Veja os resultados após votar

## ⚙️ Arquivos de Configuração

O aplicativo cria três arquivos JSON para armazenar dados:

- **enquete_config.json**: Configurações gerais (senha, status da enquete)
- **enquete_dados.json**: Dados da enquete (pergunta e opções)
- **enquete_resultados.json**: Resultados da votação

## 🛠️ Personalização

- Para alterar a senha padrão, edite a linha `"senha_professor": hash_password("admin123")` no arquivo `app.py`
- Ajuste o tempo de atualização automática modificando os valores de `time.sleep()` no código

## 🔒 Segurança

Note que este é um aplicativo local e a segurança é básica. Para uso em ambientes de produção, considere implementar medidas de segurança adicionais.

## 📝 Licença

Este projeto é livre para uso educacional.