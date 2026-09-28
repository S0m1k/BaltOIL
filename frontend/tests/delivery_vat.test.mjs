// «Добавить НДС» к ручной стоимости доставки (правки 2026-09-28).
// Чистый расчёт вырезается из index.html по маркерам @pure:delivery-vat.
// Запуск из корня репозитория:  node --test frontend/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const block = html.match(/\/\/ @pure:delivery-vat[\s\S]*?\/\/ @end:delivery-vat/);
assert.ok(block, 'в index.html нет блока @pure:delivery-vat');
const { withDeliveryVat, DELIVERY_VAT_PERCENT } =
  new Function(`${block[0]}\nreturn { withDeliveryVat, DELIVERY_VAT_PERCENT };`)();

test('ставка — 22%', () => {
  assert.equal(DELIVERY_VAT_PERCENT, 22);
});

test('3 500 → 4 270, как у зонной доставки юрлица', () => {
  assert.equal(withDeliveryVat(3500), 4270);
  assert.equal(withDeliveryVat('3200'), 3904);
});

test('копейки округляются половиной вверх, без хвостов float', () => {
  assert.equal(withDeliveryVat(1234.55), 1506.15); // 1506,151
  assert.equal(withDeliveryVat(0.25), 0.31);       // 0,305 → 0,31
  assert.equal(withDeliveryVat(100.1), 122.12);
});

test('пусто, ноль, мусор и минус — не считаем', () => {
  for (const v of ['', null, undefined, 0, '0', 'abc', -100, NaN, Infinity]) {
    assert.equal(withDeliveryVat(v), null, String(v));
  }
});
