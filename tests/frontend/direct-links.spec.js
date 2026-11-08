import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import jsQR from 'jsqr';

const preview = {
  confirmation_id: 'intent-123', expires_in: 60, name: 'Laser Thunder Nova 63',
  resource_id: 1, action: 'on', is_on: false,
  observed_at: '2026-11-08T09:00:00Z', member_id: 8, member_name: 'Example Member',
};
const confirmed = {
  operation_id: 'intent-123', phase: 'accepted', action: 'on',
  command_status: 'confirmed', member_status: 'assigned', error: null,
};

async function setup(page, { value = preview, admin = false, error = null, executeError = false, path = '/fabman/qr/first/1' } = {}) {
  const calls = [];
  await page.route('https://ha.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/fabman_static/')) {
      const file = new URL(`../../custom_components/fabman/frontend/${url.pathname.slice('/fabman_static/'.length)}`, import.meta.url);
      return route.fulfill({body: await readFile(fileURLToPath(file)), contentType: 'application/javascript'});
    }
    return route.fulfill({contentType: 'text/html', body: '<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><body style="margin:0"><script type="module" src="/fabman_static/fabman-panel.js"></script>'});
  });
  await page.exposeFunction('dispatch', async msg => {
    calls.push(msg);
    if (msg.type.endsWith('/prepare')) return error ? { _error: error } : value;
    if (msg.type.endsWith('/list')) return [{name: 'Laser <img src=x onerror=alert(1)>', entry_title: 'Workshop', path: '/fabman/qr/first/1'}];
    if (msg.type.endsWith('/execute') && executeError) return {_error: 'connection'};
    return confirmed;
  });
  await page.goto(`https://ha.test${path}`);
  await page.evaluate(async ({admin}) => {
    await customElements.whenDefined('fabman-panel');
    const panel = document.createElement('fabman-panel');
    panel.hass = {
      user: {id: 'employee', name: 'Employee', is_admin: admin}, language: 'de',
      callWS: async msg => {
        const value = await window.dispatch(msg);
        if (value._error) throw {code: value._error};
        return value;
      },
    };
    panel.route = {path: location.pathname.replace('/fabman', '')};
    document.body.append(panel);
    window.panel = panel;
  }, {admin});
  return calls;
}

test('mobile confirmation requires a user action and preserves mapped identity', async ({page}, info) => {
  const calls = await setup(page);
  await expect(page.getByRole('heading', {name: preview.name})).toBeVisible();
  await expect(page.getByText('Example Member', {exact: true})).toBeVisible();
  expect(calls.filter(c => c.type.endsWith('/execute'))).toHaveLength(0);
  expect(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: info.outputPath('machine-mobile.png'), fullPage: true});
  await page.getByRole('button', {name: 'Maschine einschalten', exact: true}).click();
  await expect(page.getByText('Schaltung bestätigt.', {exact: true})).toBeVisible();
  await expect(page.getByText('Member-Zuordnung bestätigt.', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Status aktualisieren'}).click();
  expect(calls.filter(c => c.type.endsWith('/execute'))).toEqual([
    {type: 'fabman/direct_link/execute', confirmation_id: 'intent-123'},
  ]);
});

test('door displays a release confirmation and never offers an off toggle', async ({page}) => {
  await setup(page, {value: {...preview, action: 'open', is_on: null, member_id: null, member_name: null}});
  await expect(page.getByRole('button', {name: 'Tür öffnen', exact: true})).toBeVisible();
  await expect(page.getByText('Freigabezustand (kein Türkontakt)')).toBeVisible();
  await expect(page.getByText('Fabman API-Key-Member', {exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Maschine ausschalten'})).toHaveCount(0);
});

test('running machine proposes an explicit stop', async ({page}) => {
  await setup(page, {value: {...preview, action: 'off', is_on: true}});
  await expect(page.getByRole('button', {name: 'Maschine ausschalten', exact: true})).toBeVisible();
  await expect(page.getByText('Die aktuelle Maschinennutzung wird beendet.')).toBeVisible();
});

test('cancel never sends an execute request', async ({page}) => {
  const calls = await setup(page);
  await page.getByRole('button', {name: 'Abbrechen', exact: true}).click();
  await expect(page.getByText('Abgebrochen.', {exact: true})).toBeVisible();
  expect(calls.filter(c => c.type.endsWith('/execute'))).toHaveLength(0);
});

test('disabled direct link has no confirmation button', async ({page}) => {
  const calls = await setup(page, {error: 'unavailable'});
  await expect(page.getByText('Direktlink oder Resource ist derzeit nicht verfügbar.')).toBeVisible();
  await expect(page.getByRole('button', {name: 'Maschine einschalten', exact: true})).toHaveCount(0);
  expect(calls.filter(c => c.type.endsWith('/execute'))).toHaveLength(0);
});

test('expired confirmation cannot be clicked', async ({page}) => {
  const calls = await setup(page, {value: {...preview, expires_in: 0.05}});
  await expect(page.getByText(/Bestätigung oder Ergebnis ist abgelaufen/)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Maschine einschalten', exact: true})).toHaveCount(0);
  expect(calls.filter(c => c.type.endsWith('/execute'))).toHaveLength(0);
});

test('lost execute response resumes status without replay after panel remount', async ({page}) => {
  const calls = await setup(page, {executeError: true});
  await page.getByRole('button', {name: 'Maschine einschalten', exact: true}).click();
  await expect(page.getByText(/Verbindung unterbrochen/)).toBeVisible();
  await page.evaluate(() => { window.panel.remove(); document.body.append(window.panel); });
  await expect(page.getByText('Schaltung bestätigt.', {exact: true})).toBeVisible();
  expect(calls.filter(c => c.type.endsWith('/execute'))).toHaveLength(1);
  expect(calls.filter(c => c.type.endsWith('/prepare'))).toHaveLength(1);
});

test('admin QR encodes the exact navigation link, has a quiet zone and escapes labels', async ({page}, info) => {
  await setup(page, {admin: true, path: '/fabman'});
  await expect(page.getByRole('heading', {name: 'Laser <img src=x onerror=alert(1)>'})).toBeVisible();
  const input = page.getByRole('textbox');
  await input.fill('Workshop HA'); await input.press('Tab');
  const image = page.getByRole('img', {name: 'QR-Code für die Companion App'});
  await expect(image).toBeVisible();
  const pixels = await image.evaluate(async img => {
    await img.decode();
    const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 600;
    const ctx = canvas.getContext('2d'); ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 600, 600);
    ctx.drawImage(img, 0, 0, 600, 600);
    return Array.from(ctx.getImageData(0, 0, 600, 600).data);
  });
  const decoded = jsQR(new Uint8ClampedArray(pixels), 600, 600);
  expect(decoded.data).toBe('homeassistant://navigate/fabman/qr/first/1?server=Workshop%20HA');
  expect(pixels.slice(0, 4)).toEqual([255, 255, 255, 255]);
  expect(await page.locator('fabman-panel').evaluate(p => p.shadowRoot.querySelectorAll('img').length)).toBe(1);
  await page.screenshot({path: info.outputPath('qr-mobile.png'), fullPage: true});
});

test('non-admin root does not request or display the resource directory', async ({page}) => {
  const calls = await setup(page, {path: '/fabman'});
  await expect(page.getByText('Scanne den QR-Code einer Resource.')).toBeVisible();
  expect(calls).toEqual([]);
});

test('a stale response cannot replace a newly navigated resource', async ({page}) => {
  await setup(page);
  await page.evaluate(async () => {
    window.panel.hass.callWS = async msg => {
      if (msg.type.endsWith('/prepare') && msg.resource_id === 2) {
        await new Promise(resolve => setTimeout(resolve, 100));
        return {confirmation_id:'old', expires_in:60, resource_id:2, name:'Old resource', action:'off', is_on:true};
      }
      return {confirmation_id:'new', expires_in:60, resource_id:3, name:'New resource', action:'on', is_on:false};
    };
    window.panel.route = {path: '/qr/first/2'};
    window.panel.route = {path: '/qr/first/3'};
  });
  await expect(page.getByRole('heading', {name: 'New resource'})).toBeVisible();
  await page.waitForTimeout(150);
  await expect(page.getByRole('heading', {name: 'Old resource'})).toHaveCount(0);
});
