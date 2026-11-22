import {defineConfig} from 'vite';
export default defineConfig({server:{proxy:Object.fromEntries(['/catalog','/entities','/recognitions','/itineraries','/places','/map','/health'].map(p=>[p,'http://127.0.0.1:8000']))}});
