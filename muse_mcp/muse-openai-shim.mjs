#!/usr/bin/env node
/**
 * muse-openai-shim.mjs
 * ------------------------------------------------------------------
 * OpenAI-compatible HTTP shim over the Muse browser driver.
 *
 *   GET  /v1/models              -> model list
 *   POST /v1/chat/completions    -> OpenAI chat completions (stream + non-stream)
 *   GET  /health                 -> browser/login state
 *   GET  /v1/muse/status         -> detailed driver & queue status
 *   POST /v1/muse/connect        -> ensure browser connected to muse.ai
 *   POST /v1/muse/jobs           -> submit async video generation job
 *   GET  /v1/muse/jobs/:id       -> poll video generation job status
 *   POST /v1/muse-video          -> generate video (async or await with non-blocking event loop)
 *   POST /v1/gen-video           -> generate Remotion video (non-blocking spawn)
 * ------------------------------------------------------------------
 */
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { driver } from './muse-driver.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const PORT = Number(process.env.MUSE_SHIM_PORT || 8787)
const HOST = process.env.MUSE_SHIM_HOST || '127.0.0.1'
const DEFAULT_TIMEOUT_MS = Number(process.env.MUSE_SHIM_TIMEOUT_MS || 240000)
const MODEL_IDS = (process.env.MUSE_SHIM_MODELS || 'muse-spark-1.3,muse-spark-1.3-contributor,muse,muse-video')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

const GYAN_FFMPEG_BIN = 'C:\\Users\\Ericc\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-9.0.2-full_build\\bin'
if (fs.existsSync(GYAN_FFMPEG_BIN) && !process.env.PATH.includes(GYAN_FFMPEG_BIN)) {
  process.env.PATH = `${GYAN_FFMPEG_BIN};${process.env.PATH}`
}

const log = (...a) => console.error('[muse-shim]', ...a)
const rid = () => `chatcmpl-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
const now = () => Math.floor(Date.now() / 1000)
const approxTokens = (s) => Math.max(1, Math.ceil((s || '').length / 4))

// ---------------------------------------------------------------- ffprobe helper

function getFFprobePath() {
  if (process.env.FFPROBE_PATH && fs.existsSync(process.env.FFPROBE_PATH)) return process.env.FFPROBE_PATH
  const gyanPath = path.join(GYAN_FFMPEG_BIN, 'ffprobe.exe')
  if (fs.existsSync(gyanPath)) return gyanPath
  return 'ffprobe'
}

function probeMedia(filePath) {
  return new Promise((resolve) => {
    if (!fs.existsSync(filePath)) {
      return resolve({ valid: false, error: 'File does not exist: ' + filePath })
    }
    const stat = fs.statSync(filePath)
    const proc = spawn(getFFprobePath(), [
      '-v', 'error',
      '-show_entries', 'format=duration,size,bit_rate:stream=width,height,codec_name,r_frame_rate,codec_type',
      '-of', 'json',
      filePath,
    ], { windowsHide: true })

    let stdout = ''
    let stderr = ''
    proc.stdout.on('data', (d) => { stdout += d })
    proc.stderr.on('data', (d) => { stderr += d })
    proc.on('close', (code) => {
      if (code !== 0) {
        return resolve({
          valid: true,
          duration: 0,
          size: stat.size,
          width: 1080,
          height: 1920,
          codec: path.extname(filePath).replace('.', '') || 'unknown',
          fps: null,
          audioCodec: null,
        })
      }
      try {
        const info = JSON.parse(stdout)
        const format = info.format || {}
        const videoStream = (info.streams || []).find((s) => s.codec_type === 'video') || {}
        const audioStream = (info.streams || []).find((s) => s.codec_type === 'audio') || {}
        resolve({
          valid: true,
          duration: parseFloat(format.duration || 0),
          size: parseInt(format.size || stat.size, 10),
          width: videoStream.width || 1080,
          height: videoStream.height || 1920,
          codec: videoStream.codec_name || 'unknown',
          audioCodec: audioStream.codec_name || null,
          fps: videoStream.r_frame_rate || null,
        })
      } catch (err) {
        resolve({
          valid: true,
          duration: 0,
          size: stat.size,
          width: 1080,
          height: 1920,
          codec: 'unknown',
        })
      }
    })
    proc.on('error', () => {
      resolve({
        valid: true,
        duration: 0,
        size: stat.size,
        width: 1080,
        height: 1920,
        codec: 'unknown',
      })
    })
  })
}

// ---------------------------------------------------------------- media job queue

const jobs = new Map()
const jobQueue = []
let isQueueRunning = false
let currentJobId = null

async function runJob(job) {
  job.status = 'running'
  job.startedAt = Date.now()
  log(`[job ${job.id}] Started processing. Prompt: "${(job.prompt || '').slice(0, 60)}..."`)

  const timeoutMs = job.timeoutMs || 300000
  const downloadsDir = path.join(__dirname, 'downloads')
  fs.mkdirSync(downloadsDir, { recursive: true })

  try {
    // 1. Check browser and login status
    if (!driver.isRunning()) {
      log(`[job ${job.id}] Driver not running, launching...`)
      await driver.launch()
    }

    const st = await driver.status()
    if (!st.browserRunning) {
      throw { code: 'browser_not_running', message: 'Chrome is not running. Please start Chrome with start-chrome-debug.' }
    }
    if (!st.loggedIn) {
      throw { code: 'auth_required', message: 'Not logged into Meta in Chrome. Please complete login in the opened Chrome window.' }
    }

    // 2. Snapshot existing media URLs before sending prompt
    const chatTarget = job.chat || undefined
    log(`[job ${job.id}] Snapshotting pre-existing media in chat: ${chatTarget ?? 'current'}`)
    let preMedia = { urls: [] }
    try {
      preMedia = await driver.chatMedia(chatTarget, { download: false })
    } catch (e) {
      log(`[job ${job.id}] Warning getting preMedia: ${e.message}`)
    }
    const preUrls = new Set(preMedia.urls || [])
    log(`[job ${job.id}] Found ${preUrls.size} pre-existing media URLs`)

    // 3. Send prompt with correct signature: driver.chat(prompt, opts)
    log(`[job ${job.id}] Sending prompt to Muse...`)
    const chatRes = await driver.chat(job.prompt, {
      files: job.files,
      timeoutMs,
      chat: chatTarget,
      newThread: job.newThread,
    })

    if (chatRes.needsApproval) {
      throw { code: 'approval_required', message: 'Muse requires interactive approval in Chrome UI' }
    }
    if (chatRes.timedOut) {
      throw { code: 'timeout', message: `Muse prompt execution timed out after ${timeoutMs}ms` }
    }
    if (chatRes.error) {
      throw { code: 'generation_error', message: chatRes.error }
    }

    // 4. Poll for newly generated media (checking latest assistant message and new URLs)
    log(`[job ${job.id}] Waiting for new media to appear...`)
    const deadline = Date.now() + timeoutMs
    let newUrls = []

    while (Date.now() < deadline) {
      // 4a. Check last assistant message directly
      try {
        const lastChat = await driver.readChat(3).catch(() => ({ messages: [] }))
        const lastAssistant = (lastChat.messages || []).filter(m => m.role === 'assistant').pop()
        if (lastAssistant && lastAssistant.media && lastAssistant.media.length > 0) {
          newUrls = lastAssistant.media
          log(`[job ${job.id}] Found ${newUrls.length} media URL(s) in latest assistant reply!`)
          break
        }
      } catch (e) {}

      // 4b. Check newly appearing URLs in the chat
      const currentMedia = await driver.chatMedia(chatTarget, { download: false }).catch(() => ({ urls: [] }))
      newUrls = (currentMedia.urls || []).filter((u) => !preUrls.has(u))
      if (newUrls.length > 0) {
        log(`[job ${job.id}] Detected ${newUrls.length} new media URL(s)!`)
        break
      }
      await new Promise((r) => setTimeout(r, 2500))
    }

    if (!newUrls.length) {
      throw { code: 'timeout', message: 'Timeout waiting for new video/media to be generated by Muse' }
    }

    // 5. Download ONLY the new media
    log(`[job ${job.id}] Downloading new media...`)
    const dlResult = await driver.downloadMedia(newUrls, downloadsDir)
    const validSaved = (dlResult.saved || []).filter((s) => s.file && fs.existsSync(s.file))

    if (!validSaved.length) {
      const firstErr = (dlResult.saved || [])[0]?.error || 'Unknown download failure'
      throw { code: 'download_error', message: `Failed to download media: ${firstErr}` }
    }

    const downloadedFile = validSaved[0].file

    // 6. Inspect with ffprobe
    log(`[job ${job.id}] Validating media with ffprobe: ${downloadedFile}`)
    const probe = await probeMedia(downloadedFile)
    const isImage = /.(webp|png|jpe?g|gif)$/i.test(downloadedFile) || probe.duration === 0 || probe.codec === 'webp'
    const duration = probe.duration || 0

    const elapsedSec = Math.round((Date.now() - job.startedAt) / 1000)
    job.status = 'completed'
    job.completedAt = Date.now()
    job.result = {
      ok: true,
      mediaPath: path.resolve(downloadedFile),
      downloadUrl: `/downloads/${path.basename(downloadedFile)}`,
      filename: path.basename(downloadedFile),
      duration,
      isImage,
      width: probe.width || 1080,
      height: probe.height || 1920,
      size: probe.size,
      codec: probe.codec,
      audioCodec: probe.audioCodec,
      fps: probe.fps,
      reply: chatRes.reply,
      threadUrl: chatRes.threadUrl,
      elapsedSec,
    }
    log(`[job ${job.id}] Completed successfully in ${elapsedSec}s. Media: ${downloadedFile} (${duration}s, ${probe.size} bytes)`)

  } catch (err) {
    job.status = 'failed'
    job.completedAt = Date.now()
    const code = err.code || 'internal_error'
    const message = err.message || String(err)
    job.error = { code, message }
    log(`[job ${job.id}] FAILED [${code}]: ${message}`)
  }
}

async function processQueue() {
  if (isQueueRunning) return
  isQueueRunning = true

  while (jobQueue.length > 0) {
    const nextJobId = jobQueue.shift()
    const job = jobs.get(nextJobId)
    if (job) {
      currentJobId = nextJobId
      await runJob(job)
      currentJobId = null
    }
  }

  isQueueRunning = false
}

// ---------------------------------------------------------------- prompt build

function buildPrompt(body) {
  const parts = []
  const messages = Array.isArray(body.messages) ? body.messages : []
  for (const m of messages) {
    if (!m) continue
    let c = m.content
    if (Array.isArray(c)) {
      c = c.map((p) => (typeof p === 'string' ? p : p.type === 'text' ? p.text : '')).join('')
    }
    if (typeof c === 'string' && c.trim()) parts.push(c.trim())
  }
  return parts.join('\n\n')
}

function parseToolCalls(reply) {
  if (!reply) return null
  const m = reply.match(/\{[\s\S]*"tool_calls"\s*:\s*\[[\s\S]*?\][\s\S]*?\}/)
  if (!m) return null
  try {
    const obj = JSON.parse(m[0])
    if (Array.isArray(obj.tool_calls) && obj.tool_calls.length) {
      return obj.tool_calls.map((c, i) => ({
        id: c.id || `call_${i}_${Date.now()}`,
        type: 'function',
        function: {
          name: c.name || (c.function && c.function.name) || 'unknown',
          arguments: typeof (c.arguments || (c.function && c.function.arguments)) === 'string'
            ? c.arguments || c.function.arguments
            : JSON.stringify(c.arguments || (c.function && c.function.arguments) || {}),
        },
      }))
    }
  } catch {}
  return null
}

function collectFiles(body) {
  const out = []
  if (Array.isArray(body.files)) for (const f of body.files) if (f) out.push(f)
  const messages = Array.isArray(body.messages) ? body.messages : []
  for (const m of messages) {
    if (!Array.isArray(m.content)) continue
    for (const part of m.content) {
      if (!part || typeof part === 'string') continue
      const t = part.type
      if ((t === 'image_url' || t === 'input_image') && part.image_url) {
        out.push({ url: typeof part.image_url === 'string' ? part.image_url : part.image_url.url })
      } else if (t === 'file' && part.file) {
        const f = part.file
        if (f.file_url) out.push({ url: f.file_url })
        else if (f.file_data) {
          const d = String(f.file_data)
          if (/^data:/i.test(d)) out.push({ url: d })
          else out.push({ buffer: d, name: f.filename || 'file', mimeType: f.mime_type || 'application/octet-stream' })
        }
      }
    }
  }
  return out
}

const sseHeaders = (res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
    'Access-Control-Allow-Origin': '*',
  })
}
const chunk = (id, model, created, delta, finish = null) =>
  `data: ${JSON.stringify({
    id, object: 'chat.completion.chunk', created, model,
    choices: [{ index: 0, delta, finish_reason: finish }],
  })}\n\n`

function sendError(res, status, message, type = 'invalid_request_error', code = null, param = null) {
  const body = JSON.stringify({ error: { message, type, param, code } })
  if (res.headersSent) { try { res.end() } catch {} return }
  res.writeHead(status, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
  res.end(body)
}

async function handleChat(req, res, body) {
  if (!body || typeof body !== 'object') return sendError(res, 400, 'Invalid request body')
  if (!body.model) return sendError(res, 400, 'Missing required field: model', 'invalid_request_error', null, 'model')
  if (!Array.isArray(body.messages) || !body.messages.length) {
    return sendError(res, 400, 'Missing required field: messages', 'invalid_request_error', null, 'messages')
  }

  const model = String(body.model)
  const id = rid()
  const created = now()
  const timeoutMs = Number(req.headers['x-muse-timeout-ms']) || DEFAULT_TIMEOUT_MS
  const newThread = req.headers['x-muse-thread'] === 'new'
  const prompt = buildPrompt(body)
  const wantTools = Array.isArray(body.tools) && body.tools.length > 0 && body.tool_choice !== 'none'
  const stream = body.stream === true
  const files = collectFiles(body)
  let chat = req.headers['x-muse-chat'] !== undefined ? req.headers['x-muse-chat'] : body.chat
  if (typeof chat === 'string') {
    const s = chat.trim()
    if (!s) chat = undefined
    else if (/^\d+$/.test(s)) chat = Number(s)
  }

  log(`chat model=${model} stream=${stream} tools=${wantTools} files=${files.length} target=${chat !== undefined ? chat : 'current'} promptChars=${prompt.length}`)

  try {
    let finishReason = 'stop'
    if (stream) {
      sseHeaders(res)
      let closed = false
      res.on('close', () => { closed = true })
      const write = (s) => { if (!closed) { try { res.write(s) } catch { closed = true } } }
      write(chunk(id, model, created, { role: 'assistant', content: '' }))

      if (wantTools) {
        const r = await driver.chat(prompt, { timeoutMs, newThread, files, chat })
        if (r.error) throw new Error(r.error)
        const calls = parseToolCalls(r.reply)
        if (calls && calls.length) {
          const deltas = calls.map((c, i) => ({
            index: i, id: c.id, type: 'function',
            function: { name: c.function.name, arguments: c.function.arguments },
          }))
          write(chunk(id, model, created, { tool_calls: deltas }))
          finishReason = 'tool_calls'
        } else {
          const s = r.reply || ''
          for (let i = 0; i < s.length; i += 60) write(chunk(id, model, created, { content: s.slice(i, i + 60) }))
        }
      } else {
        let emitted = ''
        const r = await driver.chatStream(prompt, {
          timeoutMs, newThread, files, chat,
          onDelta: (full) => {
            const next = full.startsWith(emitted) ? full.slice(emitted.length) : full
            emitted = full
            if (next) write(chunk(id, model, created, { content: next }))
          },
        })
        if (r.error && !emitted) throw new Error(r.error)
      }

      write(chunk(id, model, created, {}, finishReason))
      if (body.stream_options && body.stream_options.include_usage) {
        write(`data: ${JSON.stringify({
          id, object: 'chat.completion.chunk', created, model, choices: [],
          usage: { prompt_tokens: approxTokens(prompt), completion_tokens: 0, total_tokens: approxTokens(prompt) },
        })}\n\n`)
      }
      write('data: [DONE]\n\n')
      res.end()
      return
    }

    // Non-streaming
    const r = await driver.chat(prompt, { timeoutMs, newThread, files, chat })
    if (r.error && !r.reply) throw new Error(r.error)
    const calls = wantTools ? parseToolCalls(r.reply) : null

    const message = calls && calls.length
      ? { role: 'assistant', content: null, tool_calls: calls }
      : { role: 'assistant', content: r.reply || '' }

    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
    res.end(JSON.stringify({
      id, object: 'chat.completion', created, model,
      choices: [{ index: 0, message, finish_reason: calls && calls.length ? 'tool_calls' : 'stop' }],
      usage: {
        prompt_tokens: approxTokens(prompt),
        completion_tokens: approxTokens(r.reply),
        total_tokens: approxTokens(prompt) + approxTokens(r.reply),
      },
    }))
  } catch (err) {
    log('error:', err && err.message)
    sendError(res, 502, `Muse error: ${err && err.message ? err.message : String(err)}`, 'api_error')
  }
}

function readBody(req, limit = 8 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (c) => {
      data += c
      if (data.length > limit) { reject(new Error('request body too large')); req.destroy() }
    })
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

export function startShim({ port = PORT, host = HOST } = {}) {
  const server = http.createServer(async (req, res) => {
    const url = (req.url || '').split('?')[0]
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
        'Access-Control-Allow-Headers': '*',
      })
      return res.end()
    }

    try {
      // Web Dashboard UI
      if (req.method === 'GET' && (url === '/' || url === '/web')) {
        const accept = req.headers.accept || ''
        if (accept.includes('text/html') || url === '/web') {
          const htmlPath = path.join(__dirname, 'public', 'web', 'index.html')
          if (fs.existsSync(htmlPath)) {
            const html = fs.readFileSync(htmlPath, 'utf-8')
            res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
            return res.end(html)
          }
        }
        let st = { browserRunning: false, loggedIn: false }
        try { st = await driver.status() } catch {}
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({ ok: true, ...st, models: MODEL_IDS }))
      }

      const getMimeType = (filePath) => {
        const ext = path.extname(filePath).toLowerCase()
        switch (ext) {
          case '.html': return 'text/html; charset=utf-8'
          case '.css': return 'text/css; charset=utf-8'
          case '.js':
          case '.jsx':
          case '.mjs': return 'application/javascript; charset=utf-8'
          case '.json': return 'application/json; charset=utf-8'
          case '.png': return 'image/png'
          case '.jpg':
          case '.jpeg': return 'image/jpeg'
          case '.webp': return 'image/webp'
          case '.gif': return 'image/gif'
          case '.svg': return 'image/svg+xml'
          case '.mp4': return 'video/mp4'
          case '.mp3': return 'audio/mpeg'
          case '.wav': return 'audio/wav'
          default: return 'application/octet-stream'
        }
      }

      // Static files in public/web/
      if (req.method === 'GET' && (url === '/' || url === '/index.html' || url === '/styles.css' || url === '/app.jsx' || url === '/logo.png' || url.startsWith('/web/'))) {
        const fileRel = url === '/' ? 'index.html' : url.replace(/^\/web\//, '').replace(/^\//, '')
        const filePath = path.join(__dirname, 'public', 'web', fileRel)
        if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
          const mime = getMimeType(filePath)
          res.writeHead(200, { 'Content-Type': mime, 'Access-Control-Allow-Origin': '*' })
          return res.end(fs.readFileSync(filePath))
        }
      }

      // Static downloaded media files
      if (req.method === 'GET' && (url.startsWith('/downloads/') || url.startsWith('/v1/muse/downloads/'))) {
        const fileRel = url.replace(/^\/(v1\/muse\/)?downloads\//, '')
        const filePath = path.join(__dirname, 'downloads', fileRel)
        if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
          const mime = getMimeType(filePath)
          const stat = fs.statSync(filePath)
          res.writeHead(200, {
            'Content-Type': mime,
            'Content-Length': stat.size,
            'Access-Control-Allow-Origin': '*',
          })
          return fs.createReadStream(filePath).pipe(res)
        }
        return sendError(res, 404, 'File not found in downloads')
      }

      if (req.method === 'GET' && url === '/health') {
        let st = { browserRunning: false, loggedIn: false }
        try { st = await driver.status() } catch {}
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({ ok: true, ...st, models: MODEL_IDS }))
      }

      // Enhanced Detailed Status Endpoint
      if (req.method === 'GET' && url === '/v1/muse/status') {
        let st = { browserRunning: false, loggedIn: false }
        try { st = await driver.status() } catch {}
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({
          ok: true,
          ...st,
          queueLength: jobQueue.length,
          currentJobId,
          activeJobs: Array.from(jobs.values()).filter(j => j.status === 'running' || j.status === 'queued').length,
        }))
      }

      // Connect & Bring up Browser to muse.ai
      if (req.method === 'POST' && (url === '/v1/muse/connect' || url === '/v1/muse/launch-browser')) {
        let st = { browserRunning: false, loggedIn: false };
        try {
          if (!driver.isRunning()) await driver.launch();
          await driver.gotoApp();
          st = await driver.status();
        } catch (e) {
          console.error("Connect error:", e);
        }
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
        return res.end(JSON.stringify({ ok: true, message: "Browser opened to muse.ai", ...st }));
      }

      // API trigger: Video Generation Engine (Remotion) - Non-blocking async spawn
      if (req.method === 'POST' && url === '/v1/gen-video') {
        const raw = await readBody(req)
        let body = {}
        try { body = JSON.parse(raw || '{}') } catch {}

        let topic = body.topic || 'DockerExplainer'
        const prompt = body.prompt || ''
        const channelName = body.channelName || 'FierZone'
        const voice = body.voice || 'vi-VN-NamMinhNeural'
        const rate = body.rate || '+10%'

        log(`[gen-video API] topic="${topic}" channel="${channelName}" voice="${voice}"`)
        const startTime = Date.now()
        const cliScript = path.join(__dirname, 'muse-gen-video.mjs')

        const cliArgs = ['--topic', topic]
        if (prompt) cliArgs.push('--prompt', prompt)
        if (channelName) cliArgs.push('--channel', channelName)

        if (body.customScript && typeof body.customScript === 'object') {
          const scriptsDir = path.join(__dirname, 'scripts')
          fs.mkdirSync(scriptsDir, { recursive: true })
          const tempJsonPath = path.join(scriptsDir, 'temp-scenes.json')
          if (body.customScript.topicKey) topic = body.customScript.topicKey
          fs.writeFileSync(tempJsonPath, JSON.stringify(body.customScript, null, 2), 'utf-8')
          cliArgs.push('--script', tempJsonPath)
        }

        const env = { ...process.env, EDGE_TTS_VOICE: voice, EDGE_TTS_RATE: rate, CHANNEL_NAME: channelName }

        const child = spawn(process.execPath, [cliScript, ...cliArgs], {
          cwd: __dirname,
          env,
        })

        let stdout = ''
        let stderr = ''
        child.stdout.on('data', (d) => { stdout += d })
        child.stderr.on('data', (d) => { stderr += d })

        child.on('close', (status) => {
          const elapsedSec = Math.round((Date.now() - startTime) / 1000)
          if (status === 0) {
            const outPath = path.join(__dirname, 'downloads', `${topic}.mp4`)
            res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
            return res.end(JSON.stringify({ ok: true, topic, channelName, outputPath: outPath, elapsedSec, stdout }))
          } else {
            res.writeHead(500, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
            return res.end(JSON.stringify({ ok: false, error: stderr || stdout || 'Video generation failed' }))
          }
        })
        return
      }

      // ASYNC JOB API: Submit Job
      if (req.method === 'POST' && url === '/v1/muse/jobs') {
        const raw = await readBody(req)
        let body = {}
        try { body = JSON.parse(raw || '{}') } catch { return sendError(res, 400, 'Invalid JSON body') }

        const prompt = body.prompt || ''
        if (!prompt && !body.file && !body.files && !body.image_path) {
          return sendError(res, 400, 'Missing prompt or file', 'invalid_request_error')
        }

        const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const job = {
          id: jobId,
          prompt,
          files: body.file ? [body.file] : (Array.isArray(body.files) ? body.files : (body.image_path ? [body.image_path] : undefined)),
          chat: body.chat,
          newThread: body.newThread === true,
          timeoutMs: Number(body.timeoutMs || (body.timeout_sec ? body.timeout_sec * 1000 : 300000)),
          status: 'queued',
          createdAt: Date.now(),
          startedAt: null,
          completedAt: null,
          result: null,
          error: null,
        }

        jobs.set(jobId, job)
        jobQueue.push(jobId)
        processQueue()

        res.writeHead(202, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({ ok: true, jobId, status: 'queued', queuePosition: jobQueue.length }))
      }

      // ASYNC JOB API: List Recent Jobs
      if (req.method === 'GET' && url === '/v1/muse/jobs') {
        const list = Array.from(jobs.values()).slice(-50).map(j => ({
          jobId: j.id,
          status: j.status,
          prompt: (j.prompt || '').slice(0, 40),
          createdAt: j.createdAt,
          completedAt: j.completedAt,
        }))
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({ ok: true, jobs: list }))
      }

      // ASYNC JOB API: Poll Job Status
      if (req.method === 'GET' && url.startsWith('/v1/muse/jobs/')) {
        const jobId = url.replace('/v1/muse/jobs/', '').trim()
        const job = jobs.get(jobId)
        if (!job) {
          return sendError(res, 404, `Job ${jobId} not found`, 'not_found')
        }
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({
          ok: job.status !== 'failed',
          jobId: job.id,
          status: job.status,
          result: job.result,
          error: job.error,
          createdAt: job.createdAt,
          startedAt: job.startedAt,
          completedAt: job.completedAt,
        }))
      }

      // Mode 2: Meta Muse AI Video Generation (Text-to-Video / Image-to-Video AI)
      if (req.method === 'POST' && url === '/v1/muse-video') {
        const raw = await readBody(req)
        let body = {}
        try { body = JSON.parse(raw || '{}') } catch {}

        const prompt = body.prompt || 'Tạo video 9:16 nghệ thuật'
        const files = body.file ? [body.file] : (Array.isArray(body.files) ? body.files : (body.image_path ? [body.image_path] : undefined))
        const timeoutMs = Number(body.timeoutMs || (body.timeout_sec ? body.timeout_sec * 1000 : 300000))

        const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const job = {
          id: jobId,
          prompt,
          files,
          chat: body.chat,
          newThread: body.newThread === true,
          timeoutMs,
          status: 'queued',
          createdAt: Date.now(),
          startedAt: null,
          completedAt: null,
          result: null,
          error: null,
        }

        jobs.set(jobId, job)
        jobQueue.push(jobId)
        processQueue()

        if (body.async === true) {
          res.writeHead(202, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
          return res.end(JSON.stringify({ ok: true, jobId, status: 'queued' }))
        }

        const pollInterval = 1000
        const deadline = Date.now() + timeoutMs + 10000
        while (Date.now() < deadline) {
          if (job.status === 'completed') {
            res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
            return res.end(JSON.stringify(job.result))
          }
          if (job.status === 'failed') {
            res.writeHead(500, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
            return res.end(JSON.stringify({ ok: false, error: job.error?.message || 'Job failed', code: job.error?.code }))
          }
          await new Promise((r) => setTimeout(r, pollInterval))
        }

        res.writeHead(504, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({ ok: false, error: 'Request timeout waiting for job completion', code: 'timeout' }))
      }

      if (req.method === 'GET' && url === '/v1/models') {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify({
          object: 'list',
          data: MODEL_IDS.map((m) => ({ id: m, object: 'model', created: 0, owned_by: 'muse' })),
        }))
      }

      if (req.method === 'GET' && url === '/v1/muse/chats') {
        const params = new URL(req.url, 'http://localhost').searchParams
        const data = await driver.listChats(params.get('query') || undefined)
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify(data))
      }

      if (req.method === 'GET' && url === '/v1/muse/chat') {
        const params = new URL(req.url, 'http://localhost').searchParams
        const target = params.get('target')
        if (target) await driver.openChat(/^\d+$/.test(target) ? Number(target) : target)
        const data = await driver.readChat(Number(params.get('max')) || 100)
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify(data))
      }

      if (req.method === 'GET' && url === '/v1/muse/media') {
        const params = new URL(req.url, 'http://localhost').searchParams
        const target = params.get('target')
        const download = params.get('download') === '1' || params.get('download') === 'true'
        const data = await driver.chatMedia(target || undefined, { download, dir: params.get('dir') || undefined })
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' })
        return res.end(JSON.stringify(data))
      }

      if (req.method === 'POST' && url === '/v1/chat/completions') {
        const raw = await readBody(req)
        let body
        try { body = JSON.parse(raw || '{}') } catch { return sendError(res, 400, 'Invalid JSON body') }
        return handleChat(req, res, body)
      }

      sendError(res, 404, `Unknown route: ${req.method} ${url}`, 'invalid_request_error')
    } catch (err) {
      log('unhandled:', err && err.message)
      sendError(res, 500, String(err && err.message || err), 'internal_error')
    }
  })

  server.listen(port, host, () => {
    log(`OpenAI shim listening on http://${host}:${port}/v1  (models: ${MODEL_IDS.join(', ')})`)
  })
  return server
}

const isMain = process.argv[1] && import.meta.url === new URL(`file://${process.argv[1].replace(/\\/g, '/')}`).href
if (isMain || process.argv.includes('--standalone')) {
  startShim()
}
