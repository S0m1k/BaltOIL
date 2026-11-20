// Регрессия 20.11.2026: «Не могу сменить водителя» — на iPhone <select size=5>
// показывался пустой полоской без выбранного пункта, значение оставалось пустым
// и подтверждение отвечало «Выберите водителя». Теперь водители — кнопки.
// Запуск из корня репозитория:  node --test frontend/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const block = html.match(/\/\/ @pure:driver-pick[\s\S]*?\/\/ @end:driver-pick/);
assert.ok(block, 'в index.html нет блока @pure:driver-pick');
const { driverPickItems } = new Function(`${block[0]}\nreturn { driverPickItems };`)();

const DRIVERS = [
  { id: 'a', full_name: 'Бурнаев Сергей', phone: '+79001112233' },
  { id: 'b', full_name: '', email: 'drv@x.ru' },
  { id: 'c', full_name: 'Семенов Денис' },
];

test('подпись: имя и телефон, без имени — email', () => {
  const items = driverPickItems(DRIVERS, '');
  assert.equal(items[0].label, 'Бурнаев Сергей · +79001112233');
  assert.equal(items[1].label, 'drv@x.ru');
  assert.equal(items[2].label, 'Семенов Денис');
});

test('выбранный водитель отмечается, остальные нет', () => {
  const items = driverPickItems(DRIVERS, 'c');
  assert.deepEqual(items.map(i => i.selected), [false, false, true]);
});

test('пустой список и пустой выбор не ломают', () => {
  assert.deepEqual(driverPickItems([], ''), []);
  assert.deepEqual(driverPickItems(null, 'a'), []);
});

test('окно назначения не использует <select> для водителя', () => {
  const m = html.match(/function promptAssign[\s\S]*?loadDriverSelectForAssign\(\);\n\}/);
  assert.ok(m, 'нет promptAssign');
  assert.ok(!/<select[^>]*modal-driver/.test(m[0]), 'на iPhone select пустой — нужен список кнопок');
  assert.ok(m[0].includes('id="modal-driver"') && m[0].includes('modal-driver-list'));
});
