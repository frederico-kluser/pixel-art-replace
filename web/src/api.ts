// Cliente da API do studio (backend Python: python -m par studio)
// Em dev, o Vite faz proxy de /api, /sprite e /ficheiros para 127.0.0.1:8770.

export type CelulaInfo = { x: number; y: number; w: number; h: number }
export type AnaliseResumo = {
  tipo: 'sprite' | 'tilesheet'
  tamanho: [number, number]
  fundo: string
  tem_alfa: boolean
  celulas: number
  celula_px: [number, number] | null
  ia?: Record<string, unknown>
}
export type SpriteInfo = { id: number; arquivo: string; tamanho: [number, number] }
export type Progresso = { total: number; ok: number; erros: number; pendentes: number }
export type Resultado = {
  id: number
  estado: 'pendente' | 'ok' | 'erro'
  imagem?: string
  comparacao?: string
  erro?: string
  pureza?: number
  blocos_sujos?: number
}
export type Estado = {
  fase: string
  model: string
  analise: AnaliseResumo
  sprites: SpriteInfo[]
  selecionadas: number[]
  progresso: Progresso
  resultados: Resultado[]
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error((j as { erro?: string }).erro ?? `HTTP ${r.status}`)
  return j as T
}

export async function lerEstado(): Promise<Estado> {
  return api<Estado>('/api/estado')
}

export async function analisar(file: File): Promise<{
  analise: AnaliseResumo
  sprites: SpriteInfo[]
  tipo: string
}> {
  const img = await ficheiroParaB64(file)
  return api('/api/analisar', { img })
}

export async function selecionar(ids: number[]): Promise<{ selecionadas: number[] }> {
  return api('/api/selecionar', { ids })
}

export async function gerar(opts: {
  ref?: File | null
  mudanca: string
  consideracao?: string
}): Promise<{ tentativa: number; imagem: string; modelo: string; sprite: number }> {
  const body: Record<string, unknown> = {
    mudanca: opts.mudanca,
    consideracao: opts.consideracao ?? '',
  }
  if (opts.ref) body.ref = await ficheiroParaB64(opts.ref)
  return api('/api/gerar', body)
}

export async function aprovar(): Promise<{ aprovado: unknown }> {
  return api('/api/aprovar', {})
}

export async function converter(): Promise<{ em_paralelo?: number; max_paralelo?: number; fase?: string }> {
  return api('/api/converter', {})
}

export async function resultado(): Promise<{
  fase: string
  galeria: { id: number; comparacao: string; novo: string }[]
  progresso: Progresso
}> {
  return api('/api/resultado')
}

function ficheiroParaB64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(String(fr.result).split(',')[1] ?? '')
    fr.onerror = () => reject(fr.error)
    fr.readAsDataURL(f)
  })
}
