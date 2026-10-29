import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster, toast } from 'sonner'
import * as api from './api'

type Fase = 'inicio' | 'analisando' | 'analise' | 'preview' | 'aprovado' | 'convertendo' | 'pronto'

const PASSOS = [
  { n: 1, titulo: 'Imagem', desc: 'Sprite ou tilesheet' },
  { n: 2, titulo: 'Look', desc: 'Referência + mudança' },
  { n: 3, titulo: 'Prova', desc: 'Aprovar ou rejeitar' },
  { n: 4, titulo: 'Lote', desc: 'Ajustar todas' },
  { n: 5, titulo: 'Resultado', desc: 'Antes × depois' },
]

const ROTULO_FASE: Record<Fase, string> = {
  inicio: 'à espera de imagem',
  analisando: 'a analisar…',
  analise: 'pronto para gerar',
  preview: 'à sua decisão',
  aprovado: 'aprovado — pronto para o lote',
  convertendo: 'a ajustar em paralelo…',
  pronto: 'concluído',
}

export default function App() {
  const reduce = useReducedMotion()
  const [fase, setFase] = useState<Fase>('inicio')
  const [erro, setErro] = useState<string | null>(null)
  const [analise, setAnalise] = useState<api.AnaliseResumo | null>(null)
  const [sprites, setSprites] = useState<api.SpriteInfo[]>([])
  const [selecionadas, setSelecionadas] = useState<number[]>([0])
  const [tentativa, setTentativa] = useState(0)
  const [geradaUrl, setGeradaUrl] = useState<string | null>(null)
  const [progresso, setProgresso] = useState<api.Progresso>({ total: 0, ok: 0, erros: 0, pendentes: 0 })
  const [galeria, setGaleria] = useState<{ id: number; comparacao: string; novo: string }[]>([])
  const [galeriaErro, setGaleriaErro] = useState<api.Resultado[]>([])
  const [ocupado, setOcupado] = useState<string | null>(null)
  const imgRef = useRef<File | null>(null)
  const refRef = useRef<File | null>(null)
  const [mudanca, setMudanca] = useState('Redraw with a completely new outfit and look (same pose, same silhouette)')
  const [consideracao, setConsideracao] = useState('')
  const [nomeImagem, setNomeImagem] = useState('')
  const [nomeRef, setNomeRef] = useState('')

  const passoAtual = fase === 'inicio' || fase === 'analisando' ? 1 : fase === 'analise' ? 2 : fase === 'preview' ? 3 : fase === 'aprovado' || fase === 'convertendo' ? 4 : 5

  const falhou = useCallback((e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e)
    setErro(msg)
    toast.error(msg)
  }, [])

  const analisar = async () => {
    if (!imgRef.current) {
      setErro('Escolha primeiro uma imagem (sprite ou tilesheet).')
      return
    }
    setErro(null)
    setOcupado('analisar')
    try {
      const r = await api.analisar(imgRef.current)
      setAnalise(r.analise)
      setSprites(r.sprites)
      setSelecionadas(r.sprites.length ? [0] : [])
      setFase('analise')
      toast.success(`Análise: ${r.tipo === 'tilesheet' ? `tilesheet com ${r.sprites.length} sprites` : 'sprite única'}`)
    } catch (e) {
      falhou(e)
    } finally {
      setOcupado(null)
    }
  }

  const alternar = async (id: number) => {
    const nova = selecionadas.includes(id)
      ? selecionadas.filter((s) => s !== id)
      : [...selecionadas, id].sort((a, b) => a - b)
    if (nova.length === 0) {
      toast.error('Mantenha pelo menos uma sprite selecionada.')
      return
    }
    setSelecionadas(nova)
    try {
      await api.selecionar(nova)
    } catch (e) {
      falhou(e)
    }
  }

  const gerar = async () => {
    if (!refRef.current) {
      setErro('Carregue a imagem de referência (o look alvo).')
      return
    }
    setErro(null)
    setOcupado('gerar')
    try {
      const r = await api.gerar({ ref: refRef.current, mudanca, consideracao })
      setTentativa(r.tentativa)
      setGeradaUrl(`/ficheiros/${r.imagem}?t=${Date.now()}`)
      setConsideracao('')
      setFase('preview')
      toast.success(`Tentativa ${r.tentativa} gerada (${r.modelo})`)
    } catch (e) {
      falhou(e)
    } finally {
      setOcupado(null)
    }
  }

  const aprovar = async () => {
    setOcupado('aprovar')
    try {
      await api.aprovar()
      setFase('aprovado')
      toast.success('Replace aprovado — pronto para ajustar todas.')
    } catch (e) {
      falhou(e)
    } finally {
      setOcupado(null)
    }
  }

  const finalizar = useCallback(async () => {
    const r = await api.resultado()
    setProgresso(r.progresso)
    setGaleria(r.galeria)
    const estado = await api.lerEstado().catch(() => null)
    if (estado) setGaleriaErro(estado.resultados.filter((x) => x.estado === 'erro'))
    setFase('pronto')
    toast.success(`Concluído: ${r.galeria.length} sprites ajustadas.`)
  }, [])

  const converter = async () => {
    setOcupado('converter')
    try {
      const r = await api.converter()
      if (r.fase === 'pronto') {
        await finalizar()
        return
      }
      setFase('convertendo')
      toast.info(`A ajustar ${r.em_paralelo} sprites em paralelo…`)
      const t = setInterval(async () => {
        try {
          const e = await api.lerEstado()
          setProgresso(e.progresso)
          if (e.progresso.total > 0 && e.progresso.pendentes === 0) {
            clearInterval(t)
            await finalizar()
          }
        } catch {
          /* estado transitório */
        }
      }, 2000)
    } catch (e) {
      falhou(e)
    } finally {
      setOcupado(null)
    }
  }

  useEffect(() => {
    api.lerEstado()
      .then((e) => {
        setProgresso(e.progresso)
        if (e.fase === 'pronto') void finalizar().catch(() => undefined)
      })
      .catch(() => undefined)
  }, [finalizar])

  const anim = reduce
    ? {}
    : {
        initial: { opacity: 0, y: 12 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.35, ease: 'easeOut' as const },
      }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Toaster richColors position="top-right" />
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
          <div>
            <h1 className="font-heading text-xl font-semibold tracking-tight">pixel-art-replace</h1>
            <p className="text-sm text-muted-foreground">
              Sprite ou tilesheet → análise → replace com referência → aprovar → ajustar tudo em paralelo
            </p>
          </div>
          <Badge variant="secondary">
            {analise ? `${analise.tipo} · ` : ''}{ROTULO_FASE[fase]}
          </Badge>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <ol className="mb-8 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {PASSOS.map((p) => {
            const ativo = p.n === passoAtual
            const feito = p.n < passoAtual
            return (
              <li
                key={p.n}
                className={`rounded-lg border px-3 py-2 ${ativo ? 'border-primary bg-primary/10' : 'border-border'}`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-5 w-5 items-center justify-center rounded-full text-xs ${
                      feito ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {feito ? '✓' : p.n}
                  </span>
                  <span className="text-sm font-medium">{p.titulo}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{p.desc}</p>
              </li>
            )
          })}
        </ol>

        {erro && (
          <Alert variant="destructive" className="mb-6">
            <AlertTitle>Erro</AlertTitle>
            <AlertDescription>{erro}</AlertDescription>
          </Alert>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <motion.div {...anim}>
            <Card>
              <CardHeader>
                <CardTitle>1 · Imagem (sprite ou tilesheet)</CardTitle>
                <CardDescription>O MiMo v2.6 Pro analisa e o algoritmo recorta as células.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2">
                  <Label htmlFor="img">Ficheiro de imagem</Label>
                  <Input
                    id="img"
                    type="file"
                    accept="image/*"
                    onChange={(e) => {
                      imgRef.current = e.target.files?.[0] ?? null
                      setNomeImagem(imgRef.current?.name ?? '')
                    }}
                  />
                  {nomeImagem && <p className="text-xs text-muted-foreground">{nomeImagem}</p>}
                </div>
                <Button
                  onClick={analisar}
                  disabled={ocupado !== null || !imgRef.current}
                  className="w-full"
                >
                  {ocupado === 'analisar' ? 'A analisar…' : 'Analisar imagem'}
                </Button>

                {ocupado === 'analisar' && <Skeleton className="h-24 w-full" />}

                {analise && (
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={analise.tipo === 'tilesheet' ? 'default' : 'secondary'}>{analise.tipo}</Badge>
                    <Badge variant="outline">
                      {analise.tamanho[0]}×{analise.tamanho[1]}
                    </Badge>
                    <Badge variant="outline">
                      {analise.celulas} sprite{analise.celulas === 1 ? '' : 's'}
                    </Badge>
                    <Badge variant="outline">fundo {analise.fundo}</Badge>
                  </div>
                )}

                {sprites.length > 0 && (
                  <>
                    <Separator />
                    <div>
                      <p className="mb-2 text-sm font-medium">
                        2 · Escolha as sprites ({selecionadas.length} selecionada{selecionadas.length === 1 ? '' : 's'})
                      </p>
                      <div className="flex max-h-56 flex-wrap gap-2 overflow-y-auto rounded-md border border-border p-2">
                        {sprites.map((s) => {
                          const sel = selecionadas.includes(s.id)
                          const prova = selecionadas[0] === s.id
                          return (
                            <button
                              key={s.id}
                              type="button"
                              onClick={() => void alternar(s.id)}
                              aria-pressed={sel}
                              title={prova ? `sprite ${s.id} — será a usada na prova` : `sprite ${s.id}`}
                              className={`relative rounded-md border-2 p-1 transition-colors ${
                                sel ? 'border-primary' : 'border-transparent hover:border-border'
                              }`}
                            >
                              {prova && (
                                <span className="absolute -top-2 left-1 z-10 rounded bg-primary px-1 text-[10px] font-medium text-primary-foreground">
                                  prova
                                </span>
                              )}
                              <img
                                src={`/sprite/${s.id}.png`}
                                alt={`sprite ${s.id}`}
                                className="pixelated h-16 w-16 object-contain"
                              />
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>

          <motion.div {...anim}>
            <Card>
              <CardHeader>
                <CardTitle>2 · Look: referência + mudança</CardTitle>
                <CardDescription>O look alvo (referência) + o que mudar. Uma mudança por vez.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2">
                  <Label htmlFor="ref">Imagem de referência (look alvo)</Label>
                  <Input
                    id="ref"
                    type="file"
                    accept="image/*"
                    onChange={(e) => {
                      refRef.current = e.target.files?.[0] ?? null
                      setNomeRef(refRef.current?.name ?? '')
                    }}
                  />
                  {nomeRef && <p className="text-xs text-muted-foreground">{nomeRef}</p>}
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="mudanca">O que mudar (CHANGE) — em inglês, para o modelo</Label>
                  <textarea
                    id="mudanca"
                    value={mudanca}
                    onChange={(e) => setMudanca(e.target.value)}
                    rows={3}
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                  />
                </div>
                <Button
                  onClick={gerar}
                  disabled={ocupado !== null || !refRef.current || fase === 'inicio'}
                  className="w-full"
                >
                  {ocupado === 'gerar'
                    ? 'A gerar…'
                    : tentativa
                      ? `Gerar nova tentativa (${tentativa + 1})`
                      : 'Gerar replace de prova'}
                </Button>
              </CardContent>
            </Card>
          </motion.div>
        </div>

        {fase !== 'inicio' && fase !== 'analisando' && (
          <motion.div {...anim} className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>3 · Prova: aprovar ou rejeitar</CardTitle>
                <CardDescription>
                  {geradaUrl
                    ? `Tentativa ${tentativa} — compare e decida. Rejeitar com considerações gera outra tentativa.`
                    : 'A sprite de prova é a PRIMEIRA selecionada (marcada «prova»). Gere para comparar.'}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="mb-2 text-sm text-muted-foreground">original (sprite de prova {selecionadas[0] ?? 0})</p>
                    {selecionadas.length > 0 && (
                      <img
                        src={`/sprite/${selecionadas[0]}.png`}
                        alt="original"
                        className="pixelated w-full rounded-md border border-border bg-muted/30 object-contain"
                        style={{ maxHeight: 320 }}
                      />
                    )}
                  </div>
                  <div>
                    <p className="mb-2 text-sm text-muted-foreground">gerado</p>
                    {ocupado === 'gerar' ? (
                      <Skeleton className="h-64 w-full" />
                    ) : geradaUrl ? (
                      <img
                        src={geradaUrl}
                        alt="gerado"
                        className="pixelated w-full rounded-md border border-border bg-muted/30 object-contain"
                        style={{ maxHeight: 320 }}
                      />
                    ) : (
                      <div className="flex h-64 items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                        à espera de geração
                      </div>
                    )}
                  </div>
                </div>
                <div className="mt-4 grid gap-2">
                  <Label htmlFor="cons">Considerações para a retentativa (se rejeitar)</Label>
                  <textarea
                    id="cons"
                    value={consideracao}
                    onChange={(e) => setConsideracao(e.target.value)}
                    rows={2}
                    placeholder="ex.: o cinto tem de ficar preto; mantém os pés originais"
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
                  />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button variant="destructive" onClick={gerar} disabled={!geradaUrl || ocupado !== null}>
                    Rejeitar e regerar
                  </Button>
                  <Button onClick={aprovar} disabled={!geradaUrl || ocupado !== null || fase === 'aprovado'}>
                    Aprovar replace
                  </Button>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}

        {(fase === 'aprovado' || fase === 'convertendo') && (
          <motion.div {...anim} className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>4 · Lote: ajustar todas as selecionadas</CardTitle>
                <CardDescription>
                  Conversão automática em paralelo (máx. 32), cada uma re-quantizada para a paleta original.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <Button
                  onClick={converter}
                  disabled={ocupado !== null || fase === 'convertendo'}
                  className="w-full"
                >
                  {fase === 'convertendo'
                    ? `A ajustar… ${progresso.ok}/${progresso.total}`
                    : `Ajustar ${selecionadas.length} sprites em paralelo`}
                </Button>
                {progresso.total > 0 && (
                  <>
                    <Progress value={progresso.total ? (100 * progresso.ok) / progresso.total : 0} />
                    <p className="text-sm text-muted-foreground">
                      {progresso.ok}/{progresso.total} ajustadas · {progresso.erros} erros · {progresso.pendentes} pendentes
                    </p>
                  </>
                )}
              </CardContent>
            </Card>
          </motion.div>
        )}

        {fase === 'pronto' && (
          <motion.div {...anim} className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>5 · Resultado: antes × depois</CardTitle>
                <CardDescription>Cada sprite convertida, com a paleta original recuperada.</CardDescription>
              </CardHeader>
              <CardContent>
                {galeria.length === 0 && progresso.erros === 0 && (
                  <p className="text-sm text-muted-foreground">Sem sprites convertidas (todas iguais ao original).</p>
                )}
                {progresso.erros > 0 && (
                  <Alert variant="destructive" className="mb-4">
                    <AlertTitle>{progresso.erros} sprite{progresso.erros === 1 ? '' : 's'} com erro</AlertTitle>
                    <AlertDescription>
                      {(galeriaErro ?? []).map((r) => `sprite ${r.id}: ${r.erro}`).join(' · ') ||
                        'Detalhe em studio.json (campo resultados).'}
                    </AlertDescription>
                  </Alert>
                )}
                {galeria.length > 0 && (
                  <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                    {galeria.map((g, i) => (
                      <motion.a
                        key={g.id}
                        href={`/ficheiros/${g.comparacao}`}
                        target="_blank"
                        rel="noreferrer"
                        className="block"
                        {...(reduce
                          ? {}
                          : {
                              initial: { opacity: 0, y: 8 },
                              animate: { opacity: 1, y: 0 },
                              transition: { delay: i * 0.05, duration: 0.3 },
                            })}
                      >
                        <img
                          src={`/ficheiros/${g.comparacao}`}
                          alt={`comparação sprite ${g.id}`}
                          className="pixelated w-full rounded-md border border-border"
                        />
                        <p className="mt-1 text-xs text-muted-foreground">sprite {g.id}</p>
                      </motion.a>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </motion.div>
        )}
      </main>
    </div>
  )
}
