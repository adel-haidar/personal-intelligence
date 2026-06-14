import { createApp } from 'vue'
import './style.css'
import './styles/tokens.css'
import './styles/components.css'
import './styles/health-guide.css'
import './styles/finances.css'
// Initialize theme before mount to avoid flash
import './composables/useTheme'
import App from './App.vue'
import router from './router'

createApp(App).use(router).mount('#app')
