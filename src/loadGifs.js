// loadGifs.js
const gifs = import.meta.glob('./assets/COMP_GIFS/*.gif', { eager: true, import: 'default' });

const completionGifs = Object.values(gifs);

export default completionGifs;
