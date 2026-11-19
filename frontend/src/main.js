import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import './workspaceLayout.css'
import installTooltip from './utils/tooltip.js'

installTooltip()

window.cdtvStartup?.set(40, '界面资源已就绪，正在准备工作区…')
createApp(App).mount('#app')

