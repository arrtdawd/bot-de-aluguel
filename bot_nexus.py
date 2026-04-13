import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal, TextInput
import json
import asyncio
from datetime import datetime, timedelta
import os

# ==================== CONFIGURAÇÕES ====================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "contas": {},
        "alugueis": [],
        "vendas": [],
        "config": {
            "pix_chave": "seuemail@pix.com",
            "categoria_tickets": None
        }
    }

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

data = load_data()

# ==================== VERIFICAÇÃO DE ALUGUÉIS ====================
@tasks.loop(minutes=5)
async def verificar_alugueis():
    agora = datetime.now()
    for aluguel in data['alugueis']:
        if not aluguel.get('ativo', False):
            continue
        fim = datetime.fromisoformat(aluguel['fim'])
        if agora >= fim:
            aluguel['ativo'] = False
            conta_id = aluguel['conta_id']
            if conta_id in data['contas']:
                data['contas'][conta_id]['alugada'] = False
            save_data()

# ==================== EVENTOS ====================
@bot.event
async def on_ready():
    print("\n" + "="*50)
    print("🎮 BOT INICIADO COM SUCESSO!")
    print("="*50)
    print(f"📛 Nome: {bot.user.name}")
    print(f"🆔 ID: {bot.user.id}")
    print(f"🌐 Servidores: {len(bot.guilds)}")
    print("="*50)
    
    # Sincronizar comandos
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} comandos sincronizados")
        print("\n📋 Comandos disponíveis:")
        for cmd in synced:
            print(f"  /{cmd.name}")
    except Exception as e:
        print(f"❌ Erro ao sincronizar: {e}")
    
    print("\n✅ Bot está ONLINE e funcionando!")
    print("="*50 + "\n")
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="🎮 /setup para começar"
        )
    )
    
    if not verificar_alugueis.is_running():
        verificar_alugueis.start()

@bot.event
async def on_command_error(ctx, error):
    print(f"❌ Erro: {error}")

# ==================== MODALS ====================
class AddContaModal(Modal, title="📝 Adicionar Nova Conta"):
    nome = TextInput(label="Nome da Conta", placeholder="Ex: Conta VIP Mestre", max_length=50)
    login = TextInput(label="Login/Email", placeholder="email@exemplo.com", max_length=100)
    senha = TextInput(label="Senha", placeholder="senha123", max_length=50)
    preco_aluguel = TextInput(label="Preço Aluguel (R$)", placeholder="10.00", max_length=10)
    preco_venda = TextInput(label="Preço Venda (R$)", placeholder="50.00", required=False, max_length=10)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            conta_id = f"conta_{int(datetime.now().timestamp())}"
            preco_aluguel = float(self.preco_aluguel.value.replace(',', '.'))
            preco_venda = float(self.preco_venda.value.replace(',', '.')) if self.preco_venda.value else 0
            
            data['contas'][conta_id] = {
                "nome": self.nome.value,
                "login": self.login.value,
                "senha": self.senha.value,
                "preco_aluguel": preco_aluguel,
                "preco_venda": preco_venda,
                "ativa": True,
                "alugada": False,
                "vendida": False
            }
            save_data()
            
            embed = discord.Embed(
                title="✅ Conta Adicionada!",
                description=f"**{self.nome.value}** foi adicionada com sucesso!",
                color=0x00ff00
            )
            embed.add_field(name="💵 Aluguel", value=f"R$ {preco_aluguel:.2f}", inline=True)
            if preco_venda > 0:
                embed.add_field(name="💰 Venda", value=f"R$ {preco_venda:.2f}", inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erro: {e}", ephemeral=True)

class PagamentoModal(Modal, title="💳 Confirmar Pagamento"):
    codigo = TextInput(
        label="Código de Confirmação PIX",
        placeholder="Cole o código da transferência",
        style=discord.TextStyle.paragraph
    )
    
    def __init__(self, tipo, conta_id, user_id):
        super().__init__()
        self.tipo = tipo
        self.conta_id = conta_id
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ Criando ticket de pagamento...", ephemeral=True)
        await criar_ticket_pagamento(interaction, self.tipo, self.conta_id, self.user_id, self.codigo.value)

# ==================== VIEWS ====================
class MenuPrincipal(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🎮 Alugar Conta", style=discord.ButtonStyle.green, custom_id="btn_alugar")
    async def alugar_button(self, interaction: discord.Interaction, button: Button):
        await mostrar_contas_alugar(interaction)
    
    @discord.ui.button(label="💰 Comprar Conta", style=discord.ButtonStyle.blurple, custom_id="btn_comprar")
    async def comprar_button(self, interaction: discord.Interaction, button: Button):
        await mostrar_contas_comprar(interaction)
    
    @discord.ui.button(label="📊 Minhas Contas", style=discord.ButtonStyle.gray, custom_id="btn_minhas")
    async def minhas_button(self, interaction: discord.Interaction, button: Button):
        await mostrar_minhas_contas(interaction)
    
    @discord.ui.button(label="❓ Suporte", style=discord.ButtonStyle.red, custom_id="btn_suporte")
    async def suporte_button(self, interaction: discord.Interaction, button: Button):
        await criar_ticket_suporte(interaction)

class SelectConta(View):
    def __init__(self, tipo):
        super().__init__(timeout=180)
        self.tipo = tipo
        
        options = []
        for conta_id, conta in data['contas'].items():
            if not conta.get('ativa', True) or conta.get('vendida', False):
                continue
            if tipo == "aluguel" and conta.get('alugada', False):
                continue
            
            preco = conta.get('preco_aluguel', 0) if tipo == "aluguel" else conta.get('preco_venda', 0)
            if preco == 0:
                continue
            
            options.append(
                discord.SelectOption(
                    label=conta['nome'],
                    description=f"R$ {preco:.2f}",
                    value=conta_id,
                    emoji="🎮"
                )
            )
        
        if not options:
            options.append(
                discord.SelectOption(
                    label="Nenhuma conta disponível",
                    value="none",
                    emoji="❌"
                )
            )
        
        select = Select(placeholder=f"Escolha uma conta para {tipo}", options=options[:25])
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        if interaction.data['values'][0] == "none":
            await interaction.response.send_message("❌ Nenhuma conta disponível.", ephemeral=True)
            return
        
        conta_id = interaction.data['values'][0]
        await processar_pagamento(interaction, self.tipo, conta_id)

# ==================== FUNÇÕES ====================
async def mostrar_contas_alugar(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Contas para Aluguel",
        description="Escolha uma conta abaixo:",
        color=0x00ff00
    )
    
    tem_contas = False
    for conta in data['contas'].values():
        if conta.get('ativa') and not conta.get('alugada') and not conta.get('vendida') and conta.get('preco_aluguel', 0) > 0:
            tem_contas = True
            embed.add_field(
                name=conta['nome'],
                value=f"💵 R$ {conta['preco_aluguel']:.2f}/dia\n🟢 Disponível",
                inline=True
            )
    
    if not tem_contas:
        embed.description = "❌ Nenhuma conta disponível no momento."
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    await interaction.response.send_message(embed=embed, view=SelectConta("aluguel"), ephemeral=True)

async def mostrar_contas_comprar(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💰 Contas para Compra",
        description="Escolha uma conta abaixo:",
        color=0x0099ff
    )
    
    tem_contas = False
    for conta in data['contas'].values():
        if conta.get('ativa') and not conta.get('vendida') and conta.get('preco_venda', 0) > 0:
            tem_contas = True
            embed.add_field(
                name=conta['nome'],
                value=f"💵 R$ {conta['preco_venda']:.2f}\n🟢 Disponível",
                inline=True
            )
    
    if not tem_contas:
        embed.description = "❌ Nenhuma conta disponível no momento."
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    await interaction.response.send_message(embed=embed, view=SelectConta("venda"), ephemeral=True)

async def mostrar_minhas_contas(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    embed = discord.Embed(
        title="📊 Minhas Contas",
        description=f"👤 {interaction.user.mention}",
        color=0x9b59b6
    )
    
    alugueis = [a for a in data.get('alugueis', []) if a.get('user_id') == user_id and a.get('ativo')]
    vendas = [v for v in data.get('vendas', []) if v.get('user_id') == user_id]
    
    if alugueis:
        texto = ""
        for aluguel in alugueis:
            conta = data['contas'].get(aluguel['conta_id'])
            if conta:
                fim = datetime.fromisoformat(aluguel['fim'])
                restante = fim - datetime.now()
                if restante.total_seconds() > 0:
                    horas = int(restante.total_seconds() // 3600)
                    minutos = int((restante.total_seconds() % 3600) // 60)
                    texto += f"🎮 **{conta['nome']}**\n"
                    texto += f"⏰ {horas}h {minutos}min\n"
                    texto += f"🔑 `{conta['login']}`\n"
                    texto += f"🔐 `{conta['senha']}`\n\n"
        if texto:
            embed.add_field(name="🎮 Aluguéis", value=texto, inline=False)
    
    if vendas:
        texto = ""
        for venda in vendas:
            conta = data['contas'].get(venda['conta_id'])
            if conta:
                texto += f"💰 **{conta['nome']}**\n"
                texto += f"🔑 `{conta['login']}`\n"
                texto += f"🔐 `{conta['senha']}`\n\n"
        if texto:
            embed.add_field(name="💰 Compras", value=texto, inline=False)
    
    if not alugueis and not vendas:
        embed.description = "❌ Você ainda não possui contas."
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def processar_pagamento(interaction: discord.Interaction, tipo, conta_id):
    conta = data['contas'][conta_id]
    preco = conta.get('preco_aluguel', 0) if tipo == "aluguel" else conta.get('preco_venda', 0)
    
    embed = discord.Embed(
        title="💳 Pagamento via PIX",
        description=f"**Conta:** {conta['nome']}\n**Valor:** R$ {preco:.2f}",
        color=0xffaa00
    )
    
    pix = data['config'].get('pix_chave', 'Configure com /setpix')
    embed.add_field(name="📱 Chave PIX", value=f"```{pix}```", inline=False)
    embed.add_field(
        name="📋 Instruções",
        value="1️⃣ Copie a chave PIX\n2️⃣ Faça o pagamento\n3️⃣ Clique em 'Confirmar'",
        inline=False
    )
    
    class ConfirmarView(View):
        @discord.ui.button(label="✅ Confirmar Pagamento", style=discord.ButtonStyle.green)
        async def confirmar(self, interaction: discord.Interaction, button: Button):
            modal = PagamentoModal(tipo, conta_id, str(interaction.user.id))
            await interaction.response.send_modal(modal)
    
    await interaction.response.send_message(embed=embed, view=ConfirmarView(), ephemeral=True)

async def criar_ticket_pagamento(interaction, tipo, conta_id, user_id, codigo):
    guild = interaction.guild
    categoria_id = data['config'].get('categoria_tickets')
    
    if categoria_id:
        categoria = guild.get_channel(categoria_id)
    else:
        categoria = None
    
    if not categoria:
        categoria = await guild.create_category("📩 TICKETS")
        data['config']['categoria_tickets'] = categoria.id
        save_data()
    
    user = guild.get_member(int(user_id))
    ticket_name = f"💳-{user.name}"
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    ticket_channel = await categoria.create_text_channel(ticket_name, overwrites=overwrites)
    
    conta = data['contas'][conta_id]
    preco = conta.get('preco_aluguel', 0) if tipo == "aluguel" else conta.get('preco_venda', 0)
    
    embed = discord.Embed(
        title="🎫 Ticket de Pagamento",
        color=0xffaa00
    )
    embed.add_field(name="👤 Usuário", value=user.mention, inline=True)
    embed.add_field(name="🎮 Conta", value=conta['nome'], inline=True)
    embed.add_field(name="💵 Valor", value=f"R$ {preco:.2f}", inline=True)
    embed.add_field(name="💳 Código PIX", value=f"```{codigo}```", inline=False)
    
    class ApproveView(View):
        @discord.ui.button(label="✅ Aprovar", style=discord.ButtonStyle.green)
        async def aprovar(self, interaction: discord.Interaction, button: Button):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Sem permissão!", ephemeral=True)
                return
            await finalizar_transacao(interaction, tipo, conta_id, user_id, ticket_channel)
        
        @discord.ui.button(label="❌ Recusar", style=discord.ButtonStyle.red)
        async def recusar(self, interaction: discord.Interaction, button: Button):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Sem permissão!", ephemeral=True)
                return
            await interaction.response.send_message("❌ Recusado", ephemeral=True)
            await ticket_channel.send(f"❌ {user.mention} Pagamento recusado.")
            await asyncio.sleep(5)
            await ticket_channel.delete()
    
    await ticket_channel.send(embed=embed, view=ApproveView())
    await ticket_channel.send(f"📢 {user.mention} Aguarde a verificação!")

async def finalizar_transacao(interaction, tipo, conta_id, user_id, ticket_channel):
    conta = data['contas'][conta_id]
    user = interaction.guild.get_member(int(user_id))
    
    if tipo == "aluguel":
        fim = datetime.now() + timedelta(days=1)
        data['alugueis'].append({
            "user_id": user_id,
            "conta_id": conta_id,
            "inicio": datetime.now().isoformat(),
            "fim": fim.isoformat(),
            "valor": conta.get('preco_aluguel', 0),
            "ativo": True
        })
        data['contas'][conta_id]['alugada'] = True
        msg = "aluguel"
    else:
        data['vendas'].append({
            "user_id": user_id,
            "conta_id": conta_id,
            "data": datetime.now().isoformat(),
            "valor": conta.get('preco_venda', 0)
        })
        data['contas'][conta_id]['vendida'] = True
        msg = "compra"
    
    save_data()
    
    embed = discord.Embed(
        title=f"✅ {msg.capitalize()} Aprovada!",
        color=0x00ff00
    )
    embed.add_field(name="🎮 Conta", value=conta['nome'], inline=False)
    embed.add_field(name="🔑 Login", value=f"```{conta['login']}```", inline=False)
    embed.add_field(name="🔐 Senha", value=f"```{conta['senha']}```", inline=False)
    
    await interaction.response.send_message(f"✅ {msg.capitalize()} aprovada!", ephemeral=True)
    
    try:
        await user.send(embed=embed)
    except:
        pass
    
    await ticket_channel.send(f"✅ Aprovado! {user.mention}")
    await asyncio.sleep(10)
    await ticket_channel.delete()

async def criar_ticket_suporte(interaction: discord.Interaction):
    guild = interaction.guild
    categoria_id = data['config'].get('categoria_tickets')
    
    if categoria_id:
        categoria = guild.get_channel(categoria_id)
    else:
        categoria = await guild.create_category("📩 TICKETS")
        data['config']['categoria_tickets'] = categoria.id
        save_data()
    
    ticket_name = f"❓-{interaction.user.name}"
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    ticket_channel = await categoria.create_text_channel(ticket_name, overwrites=overwrites)
    
    embed = discord.Embed(
        title="🎫 Ticket de Suporte",
        description=f"Olá {interaction.user.mention}!\n\nDescreva seu problema:",
        color=0xff0000
    )
    
    await ticket_channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Ticket criado: {ticket_channel.mention}", ephemeral=True)

# ==================== COMANDOS ====================
@bot.tree.command(name="setup", description="🔧 Configurar painel")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Aluguel e Venda de Contas",
        description="Escolha uma opção:",
        color=0x00ff00
    )
    
    await interaction.channel.send(embed=embed, view=MenuPrincipal())
    await interaction.response.send_message("✅ Painel criado!", ephemeral=True)

@bot.tree.command(name="addconta", description="➕ Adicionar conta")
@discord.app_commands.checks.has_permissions(administrator=True)
async def addconta(interaction: discord.Interaction):
    await interaction.response.send_modal(AddContaModal())

@bot.tree.command(name="listarcontas", description="📋 Ver contas")
@discord.app_commands.checks.has_permissions(administrator=True)
async def listarcontas(interaction: discord.Interaction):
    if not data['contas']:
        await interaction.response.send_message("❌ Nenhuma conta cadastrada!", ephemeral=True)
        return
    
    embed = discord.Embed(title="📋 Contas", color=0x00ff00)
    
    for conta in data['contas'].values():
        status = "🔴" if conta.get('vendida') else ("🟡" if conta.get('alugada') else "🟢")
        embed.add_field(
            name=conta['nome'],
            value=f"{status} | R$ {conta.get('preco_aluguel', 0):.2f}",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="dashboard", description="📊 Estatísticas")
@discord.app_commands.checks.has_permissions(administrator=True)
async def dashboard(interaction: discord.Interaction):
    total_contas = len(data['contas'])
    alugadas = sum(1 for c in data['contas'].values() if c.get('alugada'))
    vendidas = sum(1 for c in data['contas'].values() if c.get('vendida'))
    
    lucro_total = sum(a.get('valor', 0) for a in data.get('alugueis', []))
    lucro_total += sum(v.get('valor', 0) for v in data.get('vendas', []))
    
    embed = discord.Embed(title="📊 Dashboard", color=0x9b59b6)
    embed.add_field(name="🎮 Contas", value=f"Total: {total_contas}\nAlugadas: {alugadas}\nVendidas: {vendidas}")
    embed.add_field(name="💰 Lucro Total", value=f"R$ {lucro_total:.2f}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setpix", description="💳 Configurar PIX")
@discord.app_commands.checks.has_permissions(administrator=True)
async def setpix(interaction: discord.Interaction, chave: str):
    data['config']['pix_chave'] = chave
    save_data()
    await interaction.response.send_message(f"✅ PIX configurado: `{chave}`", ephemeral=True)

@bot.tree.command(name="help", description="❓ Ajuda")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="❓ Comandos",
        description=(
            "`/setup` - Criar painel\n"
            "`/addconta` - Adicionar conta\n"
            "`/listarcontas` - Ver contas\n"
            "`/dashboard` - Estatísticas\n"
            "`/setpix` - Configurar PIX"
        ),
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==================== EXECUTAR ====================
if __name__ == "__main__":
    print("\n🔄 Iniciando bot...\n")
    
    # ⬇️⬇️⬇️ COLE SEU TOKEN AQUI ⬇️⬇️⬇️
    TOKEN = "SEU_TOKEN_AQUI"
    # ⬆️⬆️⬆️ COLE SEU TOKEN AQUI ⬆️⬆️⬆️
    
    if TOKEN == "SEU_TOKEN_AQUI":
        print("❌ ERRO: Você precisa colocar seu token!")
        print("\n📋 Passos:")
        print("1. Vá em: https://discord.com/developers/applications")
        print("2. Clique no seu bot → Bot → Reset Token")
        print("3. Copie o token")
        print("4. Cole na linha 'TOKEN = \"AQUI\"'")
        input("\nPressione ENTER para sair...")
    else:
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            print("\n❌ TOKEN INVÁLIDO!")
            print("\n✅ Verifique se:")
            print("1. Você copiou o token completo")
            print("2. Não tem espaços antes/depois")
            print("3. O token está entre aspas")
            input("\nPressione ENTER para sair...")
        except Exception as e:
            print(f"\n❌ ERRO: {e}")
            input("\nPressione ENTER para sair...")