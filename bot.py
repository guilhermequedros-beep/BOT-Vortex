import discord
from discord.ext import commands
from discord.ui import Button, View
import asyncio

# ==============================================================================
# 1. CONFIGURAÇÃO INICIAL DO BOT
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True  # Obrigatório para criação e remoção de salas temporárias
bot = commands.Bot(command_prefix="!", intents=intents)

# Lista completa com os 10 valores de apostas do seu servidor
VALORES_APOSTAS = ["1,00", "2,00", "3,00", "5,00", "10,00", "20,00", "30,00", "40,00", "50,00", "100,00"]

# Memória dinâmica para as filas (Evita que canais diferentes misturem jogadores)
filas_data = {}

# Se quiser agrupar os chats provisórios em uma categoria, coloque o ID dela aqui
ID_CATEGORIA_TEMPORARIA = 0 

def inicializar_filas_para_formato(formato):
    """Cria os espaços na memória para o canal específico"""
    for valor in VALORES_APOSTAS:
        chave = f"{formato}_{valor}"
        if chave not in filas_data:
            filas_data[chave] = {"Gel Infinito": [], "Gel Normal": []}

# ==============================================================================
# 2 e 3. BOTÕES INTERATIVOS E GERENCIAMENTO DE ENTRADA/SAÍDA
# ==============================================================================

class BotaoFila(Button):
    def __init__(self, label, style, custom_id, valor_aposta, tipo_gel, formato_canal):
        # Remove espaços do custom_id para evitar o erro "Interação Falhou" do Discord
        safe_custom_id = custom_id.replace(" ", "_")
        super().__init__(label=label, style=style, custom_id=safe_custom_id)
        self.valor_aposta = valor_aposta
        self.tipo_gel = tipo_gel
        self.formato_canal = formato_canal

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        chave = f"{self.formato_canal}_{self.valor_aposta}"
        limite = 2  # Sua regra padrão: 2 pessoas por confronto direto
        
        if chave not in filas_data:
            filas_data[chave] = {"Gel Infinito": [], "Gel Normal": []}
        
        # Ação: Sair da Fila
        if self.tipo_gel == "Sair":
            removido = False
            if user_id in filas_data[chave]["Gel Infinito"]: 
                filas_data[chave]["Gel Infinito"].remove(user_id)
                removido = True
            if user_id in filas_data[chave]["Gel Normal"]: 
                filas_data[chave]["Gel Normal"].remove(user_id)
                removido = True
                
            if removido:
                await interaction.response.send_message("Você saiu da fila!", ephemeral=True)
            else:
                await interaction.response.send_message("Você não está em nenhuma fila deste painel.", ephemeral=True)
        
        # Ação: Entrar na Fila
        else:
            # Remove se o jogador já estiver no outro gel do mesmo painel
            outro_tipo = "Gel Normal" if self.tipo_gel == "Gel Infinito" else "Gel Infinito"
            if user_id in filas_data[chave][outro_tipo]:
                filas_data[chave][outro_tipo].remove(user_id)
            
            if user_id not in filas_data[chave][self.tipo_gel]:
                filas_data[chave][self.tipo_gel].append(user_id)
                await interaction.response.send_message(f"Você entrou na fila {self.tipo_gel}!", ephemeral=True)
            else:
                await interaction.response.send_message(f"Você já está na fila {self.tipo_gel}.", ephemeral=True)
            
            # 4. GATILHO DE FILA CHEIA (Atingiu 2 competidores)
            if len(filas_data[chave][self.tipo_gel]) >= limite:
                jogadores_partida = filas_data[chave][self.tipo_gel][:limite]
                filas_data[chave][self.tipo_gel] = filas_data[chave][self.tipo_gel][limite:]
                
                # Inicia a rotina da sala privada de confirmação
                asyncio.create_task(criar_sala_confirmacao(interaction.guild, jogadores_partida, self.formato_canal, self.valor_aposta, self.tipo_gel))

        # Atualiza a Embed visual do painel correspondente
        embed_atualizada = criar_embed_fila(self.valor_aposta, self.formato_canal)
        await interaction.message.edit(embed=embed_atualizada)


class FilaView(View):
    def __init__(self, valor_aposta, formato_canal):
        super().__init__(timeout=None) # Botões permanentes (não param de funcionar)
        self.add_item(BotaoFila(label="🧬 Gel Infinito", style=discord.ButtonStyle.secondary, custom_id=f"inf_{formato_canal}_{valor_aposta}", valor_aposta=valor_aposta, tipo_gel="Gel Infinito", formato_canal=formato_canal))
        self.add_item(BotaoFila(label="🧬 Gel Normal", style=discord.ButtonStyle.secondary, custom_id=f"norm_{formato_canal}_{valor_aposta}", valor_aposta=valor_aposta, tipo_gel="Gel Normal", formato_canal=formato_canal))
        self.add_item(BotaoFila(label="❌ Sair da Fila", style=discord.ButtonStyle.danger, custom_id=f"sair_{formato_canal}_{valor_aposta}", valor_aposta=valor_aposta, tipo_gel="Sair", formato_canal=formato_canal))


def criar_embed_fila(valor, formato):
    embed = discord.Embed(title=f"👑 Filas | {formato.split(' ')[1]}", color=discord.Color.dark_embed())
    embed.add_field(name="🔸 Formato", value=formato, inline=False)
    embed.add_field(name="🔸 Valor", value=f"R$ {valor}", inline=False)
    
    chave = f"{formato}_{valor}"
    jogadores_infinito = filas_data.get(chave, {}).get("Gel Infinito", [])
    jogadores_normal = filas_data.get(chave, {}).get("Gel Normal", [])
    
    texto_jogadores = ""
    if jogadores_infinito:
        for j_id in jogadores_infinito: texto_jogadores += f"<@{j_id}> | Gel Infinito\n"
    if jogadores_normal:
        for j_id in jogadores_normal: texto_jogadores += f"<@{j_id}> | Gel Normal\n"
            
    if not texto_jogadores: texto_jogadores = "Nenhum jogador na fila"
        
    embed.add_field(name="👥 Jogadores", value=texto_jogadores, inline=False)
    return embed

# ==============================================================================
# 5 e 6. SALAS DE CONFIRMAÇÃO, PAGAMENTO E TIMER DE 30 MINUTOS
# ==============================================================================

async def criar_sala_confirmacao(guild, lista_jogadores, formato, valor, tipo_gel):
    categoria = guild.get_channel(ID_CATEGORIA_TEMPORARIA) if ID_CATEGORIA_TEMPORARIA else None
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    for j_id in lista_jogadores:
        membro = guild.get_member(j_id)
        if membro: overwrites[membro] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    canal_confirmacao = await guild.create_text_channel(name="partida-confirmar", category=categoria, overwrites=overwrites)

    mencoes = " ".join([f"<@{j_id}>" for j_id in lista_jogadores])
    await canal_confirmacao.send(f"{mencoes}")

    embed = discord.Embed(title="Aguardando Confirmações", color=0xff4500)
    embed.add_field(name="🎮 Estilo de Jogo", value=f"{formato} | {tipo_gel}", inline=False)
    embed.add_field(name="💵 Valor da Aposta", value=f"R$ {valor}", inline=False)
    embed.add_field(name="👥 Jogadores", value="\n".join([f"<@{j_id}>" for j_id in lista_jogadores]), inline=False)

    confirmados = []
    view_confirmar = View(timeout=90) # 1 minuto e meio para responder

    async def botao_confirmar_callback(interaction: discord.Interaction):
        if interaction.user.id not in lista_jogadores: return
        if interaction.user.id in confirmados: return
        
        confirmados.append(interaction.user.id)
        await interaction.response.send_message("✅ Confirmado com sucesso!", ephemeral=True)
        await canal_confirmacao.send(f"✅ **{interaction.user.mention}** confirmou a aposta! ({len(confirmados)}/2)")

        if len(confirmados) == len(lista_jogadores):
            view_confirmar.stop()
            await canal_confirmacao.send("🚀 Todos confirmaram! Gerando sala de pagamento...")
            await asyncio.sleep(3)
            await canal_confirmacao.delete()
            await criar_sala_jogo(guild, lista_jogadores, formato, valor, tipo_gel)

    async def botao_cancelar_callback(interaction: discord.Interaction):
        if interaction.user.id not in lista_jogadores: return
        view_confirmar.stop()
        await canal_confirmacao.send(f"❌ A partida foi cancelada por {interaction.user.mention}. Deletando canal em 5 segundos.")
        await asyncio.sleep(5)
        await canal_confirmacao.delete()

    btn_confirmar = Button(label="Confirmar", style=discord.ButtonStyle.success)
    btn_confirmar.callback = botao_confirmar_callback
    btn_cancelar = Button(label="Cancelar", style=discord.ButtonStyle.danger)
    btn_cancelar.callback = botao_cancelar_callback

    view_confirmar.add_item(btn_confirmar)
    view_confirmar.add_item(btn_cancelar)
    await canal_confirmacao.send(embed=embed, view=view_confirmar)


async def criar_sala_jogo(guild, lista_jogadores, formato, valor, tipo_gel):
    categoria = guild.get_channel(ID_CATEGORIA_TEMPORARIA) if ID_CATEGORIA_TEMPORARIA else None
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    for j_id in lista_jogadores:
        membro = guild.get_member(j_id)
        if membro: overwrites[membro] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    canal_jogo = await guild.create_text_channel(name=f"💰-jogo-{valor}", category=categoria, overwrites=overwrites)

    embed = discord.Embed(title="💳 Área de Pagamento & Jogo", color=0x00ff00)
    embed.description = (
        f"Bem-vindos ao canal da sua partida!\n\n"
        f"**Formato:** {formato}\n"
        f"**Configuração:** {tipo_gel}\n"
        f"**Aposta:** R$ {valor}\n\n"
        f"💚 **Partida Confirmada!** Prossigam com o pagamento junto à administração.\n"
        f"⏱️ **Aviso:** Este canal expira automaticamente em **30 minutos**."
    )
    
    mencoes = " ".join([f"<@{j_id}>" for j_id in lista_jogadores])
    await canal_jogo.send(content=mencoes, embed=embed)

    # Contagem regressiva invisível de 30 minutos (1800 segundos)
    await asyncio.sleep(1800)
    try: await canal_jogo.delete()
    except: pass

# ==============================================================================
# 1. VARREDURA AUTOMÁTICA DE PLATAFORMA E FORMATO
# ==============================================================================

@bot.command()
@commands.has_permissions(administrator=True)
async def gerarpaineis(ctx):
    """Detecta automaticamente o formato e a categoria (Mobile, Emulador ou Misto) pelo nome do canal"""
    await ctx.message.delete()
    nome_canal = ctx.channel.name.lower()
    
    # 1. Define o tamanho/vaga do formato
    if "1x1" in nome_canal: tamanho = "1x1"
    elif "2x2" in nome_canal: tamanho = "2x2"
    elif "3x3" in nome_canal: tamanho = "3x3"
    elif "4x4" in nome_canal: tamanho = "4x4"
    else: tamanho = "1x1"
        
    # 2. Define a plataforma de jogo
    if "emu" in nome_canal or "emulador" in nome_canal:
        plataforma = "Emulador"
    elif "misto" in nome_canal:
        plataforma = "Misto"
    else:
        plataforma = "Mobile" # Caso padrão se contiver 'mobile' ou similar
        
    formato_final = f"{tamanho} {plataforma}"
    inicializar_filas_para_formato(formato_final)
    
    # Imprime os 10 painéis correspondentes sequencialmente
    for valor in VALORES_APOSTAS:
        embed = criar_embed_fila(valor, formato_final)
        view = FilaView(valor, formato_final)
        await ctx.send(embed=embed, view=view)


@bot.event
async def on_ready():
    print(f"[{bot.user.name}] Monitoramento Mobile, Emulador e Misto Ativado!")

bot.run