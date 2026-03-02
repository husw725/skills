import fs from 'fs';
import { JSDOM } from 'jsdom';

const html = fs.readFileSync('./src/index.html', 'utf8');
const dom = new JSDOM(html);
global.window = dom.window;
global.document = dom.window.document;
global.requestAnimationFrame = (cb) => setTimeout(cb, 16);
global.window.HTMLCanvasElement.prototype.getContext = () => ({
    fillRect: () => {}, clearRect: () => {}, beginPath: () => {}, moveTo: () => {},
    lineTo: () => {}, fill: () => {}, arc: () => {}
});

import('./src/js/main.js').then(async () => {
    await new Promise(r => setTimeout(r, 100));
    
    // Find the instance. It might not be exposed, so we simulate clicks.
    console.log("Initial player HP:", document.getElementById('battle-hp').innerText);
    
    // Simulate pressing 'a' to attack
    const event = new dom.window.KeyboardEvent('keydown', { key: 'a' });
    
    // Wait, first we need to trigger a battle.
    // Send ArrowDown multiple times to get to the world map.
    for (let i = 0; i < 20; i++) {
        window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowDown' }));
    }
    
    // Since encounter rate is 15%, let's just force a battle if possible, or keep walking.
    let attempts = 0;
    while(document.getElementById('battle-screen').classList.contains('hidden') && attempts < 100) {
        window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowDown' }));
        window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowUp' }));
        attempts++;
    }
    
    console.log("In battle?", !document.getElementById('battle-screen').classList.contains('hidden'));
    
    // Attack
    window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'a' }));
    
    await new Promise(r => setTimeout(r, 900));
    console.log("HP after attack and enemy turn:", document.getElementById('battle-hp').innerText);
    
}).catch(console.error);
