/** 构建后把 KaTeX 发行文件复制到包内 vendor 目录，供服务端内联导出离线版。
 *  随 wheel 分发，因此使用侧不需要 Node。 */
import { cpSync, rmSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '../..')                      // 仓库根
const src = resolve(here, '../node_modules/katex/dist')
const dst = resolve(root, 'src/calcbook/vendor/katex')

if (!existsSync(src)) {
  console.error(`[vendor-katex] 找不到 ${src}，请先 npm install`)
  process.exit(1)
}

rmSync(dst, { recursive: true, force: true })
mkdirSync(dst, { recursive: true })

for (const item of ['katex.min.css', 'katex.min.js', 'contrib/auto-render.min.js']) {
  const from = resolve(src, item)
  const to = resolve(dst, item)
  mkdirSync(dirname(to), { recursive: true })
  cpSync(from, to)
}

// 字体只备 woff2：服务端内联离线导出时只用它，不重复背 woff/ttf 两份
const fontFiles = readdirSync(resolve(src, 'fonts')).filter(f => f.endsWith('.woff2'))
mkdirSync(resolve(dst, 'fonts'), { recursive: true })
for (const f of fontFiles) {
  cpSync(resolve(src, 'fonts', f), resolve(dst, 'fonts', f))
}
console.log(`[vendor-katex] 已复制 ${fontFiles.length} 个 woff2 字体与 3 个样式/脚本到 ${dst}`)
