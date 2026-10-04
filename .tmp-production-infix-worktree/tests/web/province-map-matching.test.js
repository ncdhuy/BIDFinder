const assert = require('node:assert/strict');
const fs = require('node:fs');

const script = fs.readFileSync('apps/web/script.js', 'utf8');
const start = script.indexOf('const VIETNAM_PROVINCE_NAMES');
const end = script.indexOf('function getProvinceValueEntries');
assert.ok(start >= 0 && end > start, 'province matcher section not found');

eval(`${script.slice(start, end)}
globalThis.__extractProvinceFromPlace = extractProvinceFromPlace;
globalThis.__getProvinceMapKey = getProvinceMapKey;
globalThis.__adminUnitsByKey = ADMIN_2025_BY_LEGACY_KEY;`);

const samples = [
    ['Quận 1, TP. Hồ Chí Minh', 'Thành phố Hồ Chí Minh'],
    ['Quận Ngũ Hành Sơn, Thành phố Đà Nẵng; Quận Hải Châu, Thành phố Đà Nẵng', 'Thành phố Đà Nẵng'],
    ['Tỉnh Bà Rịa - Vũng Tàu, Thành phố Vũng Tàu; Huyện Châu Đức, Tỉnh Bà Rịa - Vũng Tàu', 'Thành phố Hồ Chí Minh'],
    ['Tỉnh Bắc Giang, Thành phố Bắc Giang', 'Bắc Ninh'],
    ['Tỉnh Đăk Lăk, TP.Buôn Ma Thuột', 'Đắk Lắk'],
    ['Tỉnh Hậu Giang, Tp Vị Thanh; Huyện Châu Thành A, Tỉnh Hậu Giang', 'Thành phố Cần Thơ'],
    ['Tỉnh Ninh Thuận, TP. Phan Rang-Tháp Chàm', 'Khánh Hòa'],
    ['Tỉnh Phú Yên, TP Tuy Hoà', 'Đắk Lắk'],
    ['T.P. HCM, Thành phố Thủ Đức', 'Thành phố Hồ Chí Minh'],
    ['Thành phố Huế', 'Thành phố Huế']
];

for (const [rawLocation, expectedAdminName] of samples) {
    const province = globalThis.__extractProvinceFromPlace(rawLocation);
    const admin = globalThis.__adminUnitsByKey.get(globalThis.__getProvinceMapKey(province));
    assert.equal(
        admin?.name,
        expectedAdminName,
        `${rawLocation} -> ${province} -> ${admin?.name || 'unmapped'}`
    );
}

assert.equal(
    globalThis.__extractProvinceFromPlace('Kho bạc trung ương, địa chỉ không có tỉnh'),
    'Không xác định'
);

console.log(`Province map matching passed (${samples.length} samples)`);
