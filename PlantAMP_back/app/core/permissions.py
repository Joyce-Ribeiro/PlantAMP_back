"""
Catálogo de permissões e grupos padrão — a "matriz de acesso".

- Leitura de peptídeos (GET) é PÚBLICA e não aparece aqui.
- Cada rota protegida pede uma permissão (ex.: "peptides:import").
- Grupos recebem permissões; usuários entram em grupos.
- A matriz (grupo × permissão) fica no banco e pode ser alterada pela API
  (/api/groups/...) ou pelo painel /admin, sem mexer no código nem no .env.

Para criar uma permissão nova: adicione aqui e use
`require_permission("codigo")` na rota. No próximo start ela é cadastrada
no banco e o grupo `admin` a recebe automaticamente.
"""

PERMISSIONS: dict[str, str] = {
    "peptides:create": "Cadastrar peptídeos (POST)",
    "peptides:update": "Editar peptídeos (PUT/PATCH)",
    "peptides:delete": "Excluir peptídeos (DELETE)",
    "peptides:import": "Importar peptídeos via CSV",
    "users:read": "Ver usuários",
    "users:manage": "Criar, editar, desativar usuários e gerar links de redefinição de senha",
    "groups:read": "Ver grupos e a matriz de acesso",
    "groups:manage": "Editar grupos e a matriz de acesso",
}

# Grupo de sistema: sempre tem TODAS as permissões, não pode ser
# editado nem apagado, e a API impede que fique sem nenhum usuário ativo.
ADMIN_GROUP = "admin"

# Grupos criados no primeiro start (só se ainda não existirem).
# Depois disso, quem manda é o que está no banco.
DEFAULT_GROUPS: dict[str, dict] = {
    ADMIN_GROUP: {
        "description": "Administradores — acesso total",
        "permissions": list(PERMISSIONS),
        "is_system": True,
    },
    "curator": {
        "description": "Curadores — cadastram, editam e importam peptídeos",
        "permissions": ["peptides:create", "peptides:update", "peptides:import"],
        "is_system": False,
    },
}
