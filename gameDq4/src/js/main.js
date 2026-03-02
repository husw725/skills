import { TILE_SIZE, TILES, MAPS, MONSTERS, LEVEL_EXP, BOSS } from './core/config.js';

class Game {
    constructor() {
        this.canvas = document.getElementById('game-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.canvas.width = 512;
        this.canvas.height = 480;

        this.currentMapId = 'castle';
        this.currentMap = MAPS[this.currentMapId];

        this.player = {
            x: 4, y: 8,
            direction: 'down',
            color: '#e63946',
            stats: {
                name: '莱安', lv: 1, hp: 35, maxHp: 35, mp: 0, maxMp: 0, str: 12, def: 6, exp: 0, gold: 50
            },
            party: { hasHealie: false },
            inventory: { hasShoes: false },
            story: { bossDefeated: false, talkedToKing: false, heardRumor: false }
        };

        this.isMenuOpen = false;
        this.isDialogueOpen = false;
        this.isInBattle = false;
        this.animationFrame = 0;
        this.currentEnemy = null;

        this.init();
    }

    init() {
        window.addEventListener('keydown', (e) => this.handleInput(e));
        document.querySelectorAll('.battle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.handleBattleCommand(e.target.dataset.cmd));
        });
        
        setInterval(() => this.animationFrame = (this.animationFrame + 1) % 2, 500);
        this.gameLoop();
    }

    handleInput(e) {
        if (this.isDialogueOpen || this.isInBattle) return;

        if (e.key === 'm' || e.key === 'M' || e.key === 'Shift') {
            this.toggleStatusMenu();
            return;
        }

        if (this.isMenuOpen) return;

        let nextX = this.player.x;
        let nextY = this.player.y;
        let moved = false;

        switch(e.key) {
            case 'ArrowUp': nextY--; this.player.direction = 'up'; moved=true; break;
            case 'ArrowDown': nextY++; this.player.direction = 'down'; moved=true; break;
            case 'ArrowLeft': nextX--; this.player.direction = 'left'; moved=true; break;
            case 'ArrowRight': nextX++; this.player.direction = 'right'; moved=true; break;
            case 'Enter': case ' ': this.interact(); return;
            case 'a': if (this.isInBattle) this.handleBattleCommand('attack'); break;
            case 'r': if (this.isInBattle) this.handleBattleCommand('run'); break;
        }

        if (moved) {
            this.animationFrame = (this.animationFrame + 1) % 2;
            if (this.isWalkable(nextX, nextY)) {
                this.player.x = nextX;
                this.player.y = nextY;
                this.checkTeleport();
                
                if (this.currentMap.isWorld && !this.isInBattle) {
                    this.checkEncounter();
                }
            }
        }
    }

    isWalkable(x, y) {
        if (y < 0 || y >= this.currentMap.data.length || x < 0 || x >= this.currentMap.data[0].length) return false;
        const tile = this.currentMap.data[y][x];
        if (tile === TILES.WALL || tile === TILES.WATER || tile === TILES.MOUNTAIN || tile === TILES.CHEST) return false;
        return true;
    }

    checkTeleport() {
        if (!this.currentMap.teleports) return;
        for (let tp of this.currentMap.teleports) {
            if (this.player.x === tp.x && this.player.y === tp.y) {
                if (this.currentMapId === 'castle' && tp.targetMap === 'town' && !this.player.story.talkedToKing) {
                    this.showDialogue("卫兵（拦住去路）：莱安大人，国王陛下正等着召见您呢，请先前往王座！");
                    this.player.y--;
                    return;
                }
                if (this.currentMapId === 'town' && tp.targetMap === 'world' && !this.player.story.heardRumor) {
                    this.showDialogue("卫兵（拦住去路）：外面怪物凶猛，您最好先向镇民打听一下具体的方向和线索。");
                    this.player.y--;
                    return;
                }
                this.currentMapId = tp.targetMap;
                this.currentMap = MAPS[this.currentMapId];
                this.player.x = tp.targetX;
                this.player.y = tp.targetY;
                break;
            }
        }
    }

    checkEncounter() {
        if (Math.random() < 0.15) {
            this.startBattle(MONSTERS[Math.floor(Math.random() * MONSTERS.length)]);
        }
    }

    startBattle(monsterData) {
        this.isInBattle = true;
        this.currentEnemy = { ...monsterData };
        
        document.getElementById('battle-screen').classList.remove('hidden');
        document.getElementById('monster-name').innerText = this.currentEnemy.name;
        document.getElementById('monster-sprite').style.backgroundColor = this.currentEnemy.color;
        document.getElementById('battle-text').innerText = `出现了 ${this.currentEnemy.name}！`;
        this.updateBattleUI();
    }

    handleBattleCommand(cmd) {
        if (!this.isInBattle || this.isActionLocked) return;
        this.isActionLocked = true;

        if (cmd === 'attack') {
            const damage = Math.max(1, this.player.stats.str - Math.floor(this.currentEnemy.def / 2));
            this.currentEnemy.hp -= damage;
            document.getElementById('battle-text').innerText = `莱安攻击！给${this.currentEnemy.name}造成了${damage}点伤害。`;

            setTimeout(() => {
                if (this.currentEnemy.hp <= 0) {
                    this.winBattle();
                } else {
                    this.enemyTurn();
                }
            }, 800);
        } else if (cmd === 'run') {
            if (this.currentEnemy.isBoss) {
                document.getElementById('battle-text').innerText = `面对大眼珠怪，你无法逃跑！`;
                setTimeout(() => this.enemyTurn(), 800);
            } else {
                document.getElementById('battle-text').innerText = `莱安逃走了...`;
                setTimeout(() => this.endBattle(), 800);
            }
        } else if (cmd === 'item') {
            if (this.player.stats.hp < this.player.stats.maxHp) {
                this.player.stats.hp = Math.min(this.player.stats.maxHp, this.player.stats.hp + 20);
                document.getElementById('battle-text').innerText = `莱安使用了药草！恢复了20点HP。`;
                this.updateBattleUI();
            } else {
                document.getElementById('battle-text').innerText = `HP已经满了。`;
            }
            setTimeout(() => this.enemyTurn(), 800);
        } else if (cmd === 'defend') {
            document.getElementById('battle-text').innerText = `莱安进行了防御！(即将受到的伤害减半)`;
            this.player.isDefending = true;
            setTimeout(() => this.enemyTurn(), 800);
        }
    }

    enemyTurn() {
        let damage = Math.max(1, this.currentEnemy.str - Math.floor(this.player.stats.def / 2));
        if (this.player.isDefending) {
            damage = Math.max(1, Math.floor(damage / 2));
            this.player.isDefending = false;
        }
        
        this.player.stats.hp -= damage;
        document.getElementById('battle-text').innerText = `${this.currentEnemy.name}攻击！莱安受到了${damage}点伤害。`;
        this.updateBattleUI();

        setTimeout(() => {
            if (this.player.stats.hp <= 0) {
                alert("莱安倒下了... 游戏结束。");
                location.reload();
            } else {
                this.healieTurn();
            }
        }, 800);
    }

    healieTurn() {
        if (this.player.party.hasHealie && Math.random() < 0.5 && this.player.stats.hp < this.player.stats.maxHp) {
            const heal = 15;
            this.player.stats.hp = Math.min(this.player.stats.maxHp, this.player.stats.hp + heal);
            document.getElementById('battle-text').innerText = `荷伊明施放了恢复魔法！莱安恢复了${heal}点HP！`;
            this.updateBattleUI();
            setTimeout(() => {
                document.getElementById('battle-text').innerText = `莱安该怎么办？`;
                this.isActionLocked = false;
            }, 800);
        } else {
            document.getElementById('battle-text').innerText = `莱安该怎么办？`;
            this.isActionLocked = false;
        }
    }

    winBattle() {
        document.getElementById('battle-text').innerText = `${this.currentEnemy.name}被打倒了！\n获得了 ${this.currentEnemy.exp}点经验值和 ${this.currentEnemy.gold}G。`;
        this.player.stats.exp += this.currentEnemy.exp;
        this.player.stats.gold += this.currentEnemy.gold;
        
        let msg = "";
        let oldLv = this.player.stats.lv;
        while (this.player.stats.lv < LEVEL_EXP.length - 1 && this.player.stats.exp >= LEVEL_EXP[this.player.stats.lv]) {
            this.player.stats.lv++;
            this.player.stats.maxHp += 5;
            this.player.stats.str += 3;
            this.player.stats.def += 2;
            this.player.stats.hp = this.player.stats.maxHp; // 升级满血
            msg += `\n等级提升到了 Lv${this.player.stats.lv}！力量+3, 守备+2, 最大HP+5！`;
        }

        if (this.currentEnemy.isBoss) {
            this.player.story.bossDefeated = true;
            msg += `\n你击败了首领大眼珠怪，救出了被抓走的孩子们！请回王宫复命吧！`;
        }

        if (msg) document.getElementById('battle-text').innerText += msg;
        
        setTimeout(() => this.endBattle(), msg ? 2000 : 1000);
    }

    endBattle() {
        this.isInBattle = false;
        this.isActionLocked = false;
        this.currentEnemy = null;
        document.getElementById('battle-screen').classList.add('hidden');
        if (this.player.story.bossDefeated && this.currentMapId === 'cave') {
            this.currentMap.npcs = this.currentMap.npcs.filter(n => n.type !== 'boss');
        }
    }

    interact() {
        let checkX = this.player.x; let checkY = this.player.y;
        if (this.player.direction === 'up') checkY--; else if (this.player.direction === 'down') checkY++;
        else if (this.player.direction === 'left') checkX--; else if (this.player.direction === 'right') checkX++;
        
        if (this.currentMap.npcs) {
            for (let i=0; i < this.currentMap.npcs.length; i++) {
                let npc = this.currentMap.npcs[i];
                if (npc.x === checkX && npc.y === checkY) {
                    
                    if (npc.type === 'king') {
                        if (this.player.story.bossDefeated) {
                            this.showDialogue("国王：干得好！莱安！你救回了孩子们！\n这就是巴特兰第一战士的实力！\n\n【第一章：王宫的战士们 完】");
                            return;
                        } else {
                            this.player.story.talkedToKing = true;
                        }
                    }

                    if (npc.text.includes("听说北边")) {
                        this.player.story.heardRumor = true;
                    }

                    this.showDialogue(npc.text);
                    
                    if (npc.event === 'join_healie' && !this.player.party.hasHealie) {
                        this.player.party.hasHealie = true;
                        this.currentMap.npcs.splice(i, 1); // 荷伊明从地图消失
                    } else if (npc.event === 'get_shoes' && !this.player.inventory.hasShoes) {
                        this.player.inventory.hasShoes = true;
                        this.currentMap.npcs.splice(i, 1); // 宝箱开启
                        this.currentMap.data[checkY][checkX] = TILES.FLOOR; // 将宝箱瓦片变成地板
                    } else if (npc.event === 'start_boss') {
                        if (this.player.inventory.hasShoes) {
                            setTimeout(() => this.startBattle(BOSS), 100);
                        } else {
                            this.showDialogue("这座塔需要飞天鞋才能飞上去。\n大眼珠怪在顶层嘲笑着你。");
                        }
                    }
                    return;
                }
            }
        }
    }

    showDialogue(text) {
        this.isDialogueOpen = true;
        const box = document.getElementById('dialogue-box');
        const content = document.getElementById('dialogue-text');
        content.innerText = text; box.classList.remove('hidden');
        const closeHandler = (e) => { if (e.key === 'Enter' || e.key === ' ') { box.classList.add('hidden'); this.isDialogueOpen = false; window.removeEventListener('keydown', closeHandler); } };
        setTimeout(() => window.addEventListener('keydown', closeHandler), 100);
    }

    toggleStatusMenu() {
        this.isMenuOpen = !this.isMenuOpen;
        const menu = document.getElementById('status-menu');
        if (this.isMenuOpen) { this.updateStatusMenuUI(); menu.classList.remove('hidden'); }
        else menu.classList.add('hidden');
    }

    updateStatusMenuUI() {
        const s = this.player.stats;
        document.getElementById('stat-name').innerText = s.name; document.getElementById('stat-lv').innerText = s.lv;
        document.getElementById('stat-hp').innerText = `${s.hp}/${s.maxHp}`; document.getElementById('stat-mp').innerText = `${s.mp}/${s.maxMp}`;
        document.getElementById('stat-str').innerText = s.str; document.getElementById('stat-def').innerText = s.def;
        document.getElementById('stat-exp').innerText = s.exp; document.getElementById('stat-gold').innerText = `${s.gold} G`;
        
        let extraInfo = "";
        if (this.player.party.hasHealie) extraInfo += "<br/>同伴: 荷伊明 (战斗回血)";
        if (this.player.inventory.hasShoes) extraInfo += "<br/>物品: 飞天鞋";
        
        let p = document.getElementById('stat-extra');
        if(!p) {
            p = document.createElement('p');
            p.id = 'stat-extra';
            p.style.marginTop = '10px';
            p.style.color = '#ffd166';
            document.getElementById('status-menu').appendChild(p);
        }
        p.innerHTML = extraInfo;
    }

    drawMap() {
        for (let row = 0; row < this.currentMap.data.length; row++) {
            for (let col = 0; col < this.currentMap.data[row].length; col++) {
                const tile = this.currentMap.data[row][col];
                let px = col * TILE_SIZE;
                let py = row * TILE_SIZE;

                this.ctx.fillStyle = '#000';
                this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);

                switch(tile) {
                    case TILES.FLOOR:
                        this.ctx.fillStyle = '#6b705c';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#a5a58d';
                        this.ctx.fillRect(px, py, TILE_SIZE/2, TILE_SIZE/2);
                        this.ctx.fillRect(px + TILE_SIZE/2, py + TILE_SIZE/2, TILE_SIZE/2, TILE_SIZE/2);
                        break;
                    case TILES.WALL:
                        this.ctx.fillStyle = '#6c584c';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#a98467';
                        this.ctx.fillRect(px + 2, py + 2, TILE_SIZE - 4, TILE_SIZE/2 - 4);
                        this.ctx.fillRect(px + 2, py + TILE_SIZE/2 + 2, TILE_SIZE/2 - 4, TILE_SIZE/2 - 4);
                        this.ctx.fillRect(px + TILE_SIZE/2 + 2, py + TILE_SIZE/2 + 2, TILE_SIZE/2 - 4, TILE_SIZE/2 - 4);
                        break;
                    case TILES.GRASS:
                        this.ctx.fillStyle = '#386641';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#6a994e';
                        this.ctx.fillRect(px + 4, py + 4, 4, 4);
                        this.ctx.fillRect(px + 16, py + 20, 4, 4);
                        this.ctx.fillRect(px + 24, py + 8, 4, 4);
                        break;
                    case TILES.WATER:
                        this.ctx.fillStyle = '#118ab2';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#00b4d8';
                        if (this.animationFrame === 0) {
                            this.ctx.fillRect(px + 4, py + 8, 12, 2);
                            this.ctx.fillRect(px + 16, py + 24, 12, 2);
                        } else {
                            this.ctx.fillRect(px + 8, py + 8, 12, 2);
                            this.ctx.fillRect(px + 12, py + 24, 12, 2);
                        }
                        break;
                    case TILES.DIRT:
                        this.ctx.fillStyle = '#9c6644';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#b08968';
                        this.ctx.fillRect(px + 6, py + 6, 6, 6);
                        this.ctx.fillRect(px + 20, py + 18, 6, 6);
                        break;
                    case TILES.EXIT:
                        this.ctx.fillStyle = '#111';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#333';
                        this.ctx.fillRect(px + 8, py + 8, TILE_SIZE - 16, TILE_SIZE - 16);
                        break;
                    case TILES.MOUNTAIN:
                        this.ctx.fillStyle = '#4a4e69';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#9a8c98';
                        this.ctx.beginPath();
                        this.ctx.moveTo(px + TILE_SIZE/2, py + 4);
                        this.ctx.lineTo(px + 4, py + TILE_SIZE);
                        this.ctx.lineTo(px + TILE_SIZE - 4, py + TILE_SIZE);
                        this.ctx.fill();
                        break;
                    case TILES.FOREST:
                        this.ctx.fillStyle = '#2b9348';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#007f5f';
                        this.ctx.beginPath();
                        this.ctx.arc(px + TILE_SIZE/2, py + TILE_SIZE/2, TILE_SIZE/2 - 2, 0, Math.PI * 2);
                        this.ctx.fill();
                        break;
                    case TILES.TOWN:
                        this.ctx.fillStyle = '#8b4513';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#d4a373';
                        this.ctx.fillRect(px + 8, py + 8, 16, 16);
                        break;
                    case TILES.CAVE:
                        this.ctx.fillStyle = '#333';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#000';
                        this.ctx.beginPath();
                        this.ctx.arc(px + TILE_SIZE/2, py + TILE_SIZE/2 + 4, 10, 0, Math.PI * 2);
                        this.ctx.fill();
                        break;
                    case TILES.CHEST:
                        this.ctx.fillStyle = '#6b705c'; // floor bg
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                        this.ctx.fillStyle = '#b08d57'; // wood color
                        this.ctx.fillRect(px + 4, py + 8, 24, 16);
                        this.ctx.fillStyle = '#ffd166'; // gold lock
                        this.ctx.fillRect(px + 14, py + 14, 4, 4);
                        break;
                    default:
                        this.ctx.fillStyle = '#000';
                        this.ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);
                }
            }
        }
    }

    drawNPCs() {
        if (!this.currentMap.npcs) return;
        for (let npc of this.currentMap.npcs) {
            let px = npc.x * TILE_SIZE;
            let py = npc.y * TILE_SIZE;

            if (npc.type === 'king') {
                this.ctx.fillStyle = '#9e2a2b';
                this.ctx.fillRect(px + 4, py + 12, 24, 18);
                this.ctx.fillStyle = '#ffcdb2';
                this.ctx.fillRect(px + 8, py + 8, 16, 12);
                this.ctx.fillStyle = '#ffd166';
                this.ctx.beginPath();
                this.ctx.moveTo(px + 6, py + 8);
                this.ctx.lineTo(px + 10, py + 2);
                this.ctx.lineTo(px + 16, py + 6);
                this.ctx.lineTo(px + 22, py + 2);
                this.ctx.lineTo(px + 26, py + 8);
                this.ctx.fill();
                this.ctx.fillStyle = '#fff';
                this.ctx.fillRect(px + 8, py + 16, 16, 8);
            } else if (npc.type === 'monster') {
                this.ctx.fillStyle = '#800080';
                this.ctx.fillRect(px + 6, py + 6, 20, 20);
                this.ctx.fillStyle = '#fff';
                this.ctx.fillRect(px + 10, py + 10, 4, 4);
                this.ctx.fillRect(px + 18, py + 10, 4, 4);
            } else if (npc.type === 'healie') {
                // 荷伊明 (回血史莱姆 - 绿色带触手)
                this.ctx.fillStyle = '#00fa9a';
                this.ctx.beginPath();
                this.ctx.arc(px + TILE_SIZE/2, py + TILE_SIZE/2, 8, 0, Math.PI * 2);
                this.ctx.fill();
                this.ctx.fillRect(px + 10, py + TILE_SIZE/2 + 6, 2, 6); // 左触手
                this.ctx.fillRect(px + 20, py + TILE_SIZE/2 + 6, 2, 6); // 右触手
                this.ctx.fillStyle = '#000';
                this.ctx.fillRect(px + 12, py + 14, 2, 2);
                this.ctx.fillRect(px + 18, py + 14, 2, 2);
            } else if (npc.type === 'boss') {
                // 大眼珠怪
                this.ctx.fillStyle = '#ff4500';
                this.ctx.fillRect(px + 2, py + 2, 28, 28);
                // 大眼睛
                this.ctx.fillStyle = '#fff';
                this.ctx.fillRect(px + 6, py + 6, 20, 12);
                this.ctx.fillStyle = '#000';
                this.ctx.fillRect(px + 12, py + 8, 8, 8);
                this.ctx.fillStyle = '#f00';
                this.ctx.fillRect(px + 14, py + 10, 4, 4); // 红色瞳孔
            } else if (npc.type === 'chest') {
                // Chest in NPC list
                this.ctx.fillStyle = '#b08d57';
                this.ctx.fillRect(px + 4, py + 8, 24, 16);
                this.ctx.fillStyle = '#ffd166';
                this.ctx.fillRect(px + 14, py + 14, 4, 4);
            } else {
                this.ctx.fillStyle = '#457b9d';
                this.ctx.fillRect(px + 6, py + 14, 20, 16);
                this.ctx.fillStyle = '#ffcdb2';
                this.ctx.fillRect(px + 8, py + 4, 16, 12);
                this.ctx.fillStyle = '#000';
                this.ctx.fillRect(px + 12, py + 8, 2, 2);
                this.ctx.fillRect(px + 18, py + 8, 2, 2);
            }
        }
    }

    drawPlayer() {
        if (this.isInBattle) return;
        let px = this.player.x * TILE_SIZE;
        let py = this.player.y * TILE_SIZE;

        // 如果荷伊明加入了，跟在后面走 (简化版，直接画在玩家左上方)
        if (this.player.party.hasHealie) {
            this.ctx.fillStyle = '#00fa9a';
            this.ctx.beginPath();
            this.ctx.arc(px, py, 6, 0, Math.PI * 2);
            this.ctx.fill();
        }

        this.ctx.fillStyle = this.player.color; 
        this.ctx.fillRect(px + 6, py + 12, 20, 18);
        
        this.ctx.fillStyle = '#333';
        if (this.animationFrame === 0) {
            this.ctx.fillRect(px + 8, py + 28, 6, 4);
            this.ctx.fillRect(px + 18, py + 28, 6, 4);
        } else {
            this.ctx.fillRect(px + 8, py + 26, 6, 6);
            this.ctx.fillRect(px + 18, py + 28, 6, 4);
        }

        this.ctx.fillStyle = '#adb5bd'; 
        this.ctx.fillRect(px + 8, py + 2, 16, 10);
        this.ctx.fillStyle = '#ffcdb2'; 
        this.ctx.fillRect(px + 10, py + 6, 12, 6);

        this.ctx.fillStyle = '#000';
        if (this.player.direction === 'down') {
            this.ctx.fillRect(px + 12, py + 8, 2, 2);
            this.ctx.fillRect(px + 18, py + 8, 2, 2);
            this.ctx.fillStyle = '#ffd166';
            this.ctx.fillRect(px + 2, py + 16, 6, 2);
        } else if (this.player.direction === 'up') {
            this.ctx.fillStyle = '#adb5bd';
            this.ctx.fillRect(px + 10, py + 6, 12, 6); 
        } else if (this.player.direction === 'left') {
            this.ctx.fillRect(px + 12, py + 8, 2, 2);
            this.ctx.fillStyle = '#dee2e6';
            this.ctx.fillRect(px - 2, py + 16, 10, 4);
        } else if (this.player.direction === 'right') {
            this.ctx.fillRect(px + 18, py + 8, 2, 2);
            this.ctx.fillStyle = '#dee2e6';
            this.ctx.fillRect(px + 24, py + 16, 10, 4);
        }
    }

    gameLoop() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.drawMap();
        this.drawNPCs();
        this.drawPlayer();
        requestAnimationFrame(() => this.gameLoop());
    }
}

new Game();
