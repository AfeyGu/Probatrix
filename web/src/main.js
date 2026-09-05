import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'katex/dist/katex.min.css'
import App from './App.vue'
import { init } from './store'
import { ElMessage } from 'element-plus'

const app = createApp(App)
app.use(ElementPlus)
app.mount('#app')

init().catch(e => ElMessage.error(`初始化失败：${e.message}`))
