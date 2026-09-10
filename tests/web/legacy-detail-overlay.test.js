const assert = require('node:assert/strict');
const fs = require('node:fs');

const style = fs.readFileSync('apps/web/style.css', 'utf8');
const script = fs.readFileSync('apps/web/script.js', 'utf8');

assert.match(
    style,
    /#legacy-row-detail\.legacy-row-detail\s*\{[\s\S]*?position:\s*fixed;[\s\S]*?inset:\s*0;[\s\S]*?margin:\s*0;[\s\S]*?border:\s*0;[\s\S]*?border-radius:\s*0;/
);
assert.match(
    script,
    /if \(detail\.parentElement !== document\.body\)\s*\{[\s\S]*?document\.body\.appendChild\(detail\);/
);

console.log('Legacy detail overlay viewport contract passed');
