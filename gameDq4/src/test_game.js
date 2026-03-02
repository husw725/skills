// Tester script: Validate game logic and data integrity

// Using fs to read the files since they use ES modules and might fail in simple Node environment without package.json type: module setup
const fs = require('fs');

console.log("=== 启动测试：勇者斗恶龙4 Web版 ===");

try {
    const configCode = fs.readFileSync('js/core/config.js', 'utf8');
    const mainCode = fs.readFileSync('js/main.js', 'utf8');

    console.log("✅ 代码文件读取成功");

    // 简单检查语法与缺失的导出
    if (!configCode.includes('export const MAPS')) {
        throw new Error("config.js 缺少 MAPS 导出");
    }
    if (!configCode.includes('export const MONSTERS')) {
        throw new Error("config.js 缺少 MONSTERS 导出");
    }
    if (!configCode.includes('export const BOSS')) {
        throw new Error("config.js 缺少 BOSS 导出");
    }

    console.log("✅ 核心数据结构存在");

    // 检查地图出口与连接逻辑
    console.log("正在验证地图传送逻辑...");
    const mapMatch = configCode.match(/targetMap:\s*'([^']+)'/g);
    if (mapMatch) {
        const targets = mapMatch.map(m => m.match(/'([^']+)'/)[1]);
        const validMaps = ['castle', 'town', 'world', 'cave'];
        targets.forEach(target => {
            if (!validMaps.includes(target)) {
                throw new Error(`发现无效的地图传送目标: ${target}`);
            }
        });
        console.log("✅ 地图传送点验证通过 (没有死链)");
    }

    // 检查战斗数值平衡
    console.log("正在验证怪物与角色数值平衡...");
    const monstersMatch = configCode.match(/name:\s*'([^']+)',\s*hp:\s*(\d+),\s*str:\s*(\d+),\s*def:\s*(\d+)/g);
    if (monstersMatch) {
        monstersMatch.forEach(m => {
            const data = m.match(/name:\s*'([^']+)',\s*hp:\s*(\d+),\s*str:\s*(\d+),\s*def:\s*(\d+)/);
            if (parseInt(data[3]) > 20) {
                console.warn(`⚠️ 警告：怪物 ${data[1]} 的攻击力过高，初期玩家容易死亡！`);
            }
        });
    }

    // 检查主循环逻辑中的防呆设计
    if (!mainCode.includes('this.isDialogueOpen || this.isInBattle')) {
        console.warn("⚠️ 警告：玩家在对话或战斗时可能未被锁定移动！");
    } else {
        console.log("✅ 移动锁定逻辑验证通过 (对话与战斗时禁止移动)");
    }

    console.log("=== 所有静态测试通过，游戏数据完整！ ===");

} catch (e) {
    console.error("❌ 测试失败: ", e.message);
    process.exit(1);
}
