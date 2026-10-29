"""pixel-art-replace — substitui o look de sprites/pixel art com IA, do upload à aprovação.

Fluxo: enviar UMA sprite ou uma TILESHEET → o MiMo v2.6 Pro analisa →
  · sprite única: expande para a resolução das ferramentas de geração e mostra o resultado;
  · tilesheet: recorta as sprites, o utilizador escolhe, a escolhida é expandida e o replace
    é feito com a imagem de referência; aprovado, TODAS são ajustadas em paralelo.
"""

__version__ = "0.1.0"
