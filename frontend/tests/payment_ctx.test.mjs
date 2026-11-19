// Регрессия 19.11.2026: заявка «От организации (без клиента)» у юрлица с
// отгрузкой в долг уходила со статичной «Предоплатой» → «ждём оплату».
// Чистая логика вырезается из index.html по маркерам @pure:payment-ctx.
// Запуск из корня репозитория:  node --test frontend/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const block = html.match(/\/\/ @pure:payment-ctx[\s\S]*?\/\/ @end:payment-ctx/);
assert.ok(block, 'в index.html нет блока @pure:payment-ctx');
const { paymentOptionsClientId, paymentCtxKey, paymentRadiosMatch } = new Function(
  `${block[0]}\nreturn { paymentOptionsClientId, paymentCtxKey, paymentRadiosMatch };`,
)();

const ADMIN = 'admin-1';
const ORG = 'org-credit';

test('«От организации (без клиента)»: условия организации грузятся через сотрудника', () => {
  assert.equal(paymentOptionsClientId('__org__', true, ADMIN, ORG), ADMIN);
});

test('«От организации» без выбранной организации и разовый клиент — грузить нечего', () => {
  assert.equal(paymentOptionsClientId('__org__', true, ADMIN, ''), null);
  assert.equal(paymentOptionsClientId('__oneoff__', true, ADMIN, ORG), null);
  assert.equal(paymentOptionsClientId('', true, ADMIN, ORG), null);
});

test('обычный клиент у сотрудника и клиент сам себе', () => {
  assert.equal(paymentOptionsClientId('client-7', true, ADMIN, ORG), 'client-7');
  assert.equal(paymentOptionsClientId('', false, 'client-7', ORG), 'client-7');
});

test('статичная «Предоплата» (варианты не загружены) не отправляется — тип решает сервер', () => {
  const expected = paymentCtxKey(paymentOptionsClientId('__org__', true, ADMIN, ORG), ORG);
  assert.equal(paymentRadiosMatch(undefined, expected), false);
});

test('варианты загружены для другой организации — тип не отправляется', () => {
  const rendered = paymentCtxKey(ADMIN, 'org-other');
  assert.equal(paymentRadiosMatch(rendered, paymentCtxKey(ADMIN, ORG)), false);
});

test('варианты загружены для этих клиента и организации — выбор пользователя уходит', () => {
  const key = paymentCtxKey(ADMIN, ORG);
  assert.equal(paymentRadiosMatch(key, key), true);
});

test('пустой ожидаемый ключ никогда не совпадает', () => {
  assert.equal(paymentRadiosMatch('', ''), false);
  assert.equal(paymentCtxKey(null, ORG), '');
});
