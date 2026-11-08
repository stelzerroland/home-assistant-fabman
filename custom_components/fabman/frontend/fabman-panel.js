import qrcode from './vendor/qrcode.mjs';

const TEXT = {
  de: {
    title: 'Fabman', intro: 'Resource steuern', scan: 'Scanne den QR-Code einer Resource.',
    links: 'Freigegebene Direktlinks', empty: 'Keine Direktlinks aktiviert. Freigabe unter Einstellungen → Geräte & Dienste → Fabman → Konfigurieren → Direktlinks.',
    on: 'Maschine einschalten', off: 'Maschine ausschalten', open: 'Tür öffnen',
    question: 'Möchtest du diese Aktion ausführen?', cancel: 'Abbrechen',
    state: 'Beobachteter Zustand', active: 'AN', inactive: 'AUS', unknown: 'Unbekannt',
    door: 'Freigabezustand (kein Türkontakt)', actor: 'Du startest die Nutzung als',
    api: 'Fabman API-Key-Member', stop: 'Die aktuelle Maschinennutzung wird beendet.',
    loading: 'Zustand wird geprüft …', sending: 'Befehl wird vorbereitet …',
    accepted: 'Befehl angenommen. Bestätigung wird abgewartet …',
    confirmed: 'Schaltung bestätigt.', opened: 'Öffnungsfreigabe bestätigt.',
    assigned: 'Member-Zuordnung bestätigt.', assignmentPending: 'Member-Zuordnung wird geprüft …',
    attribution_unconfirmed: 'Der Befehl wurde angenommen, aber die Member-Zuordnung konnte nicht bestätigt werden. Bitte das Fabman-Aktivitätsprotokoll prüfen.',
    timeout: 'Befehl gesendet, aber nicht bestätigt. Zustand vor einem weiteren Versuch prüfen.',
    superseded: 'Ein anderer Befehl hat diesen Vorgang abgelöst. Bitte den aktuellen Zustand prüfen.',
    rejected: 'Fabman hat den Befehl abgelehnt. Berechtigung, Paket und Member-Zuordnung prüfen.',
    uncertain: 'Der Ausgang ist unklar. Die Resource könnte bereits geschaltet sein. Vor einem weiteren Versuch den Zustand und das Fabman-Protokoll prüfen.',
    interrupted: 'Vorgang durch Neuladen der Integration unterbrochen. Der Befehl könnte bereits gesendet worden sein. Zustand prüfen.',
    changed: 'Zustand oder Zuordnung hat sich geändert. Bitte neu prüfen und erneut bestätigen.',
    expired: 'Bestätigung oder Ergebnis ist abgelaufen. Vor einem weiteren Versuch den aktuellen Zustand prüfen.',
    unknown_state: 'Der Maschinenzustand ist unbekannt. Eine Umschaltung ist derzeit nicht möglich.',
    unavailable: 'Direktlink oder Resource ist derzeit nicht verfügbar.',
    unauthorized: 'Du darfst diese Resource nicht steuern.', invalid_mapping: 'Dein Fabman-User-Mapping konnte nicht geprüft werden.',
    busy: 'Derzeit sind zu viele Bestätigungen offen. Bitte später erneut versuchen.',
    connection: 'Verbindung unterbrochen. Es wird kein Befehl erneut gesendet.',
    check: 'Neu prüfen', status: 'Status aktualisieren', cancelled: 'Abgebrochen.',
    browser: 'Browser-Link kopieren', app: 'App-Link kopieren', download: 'QR als SVG speichern',
    print: 'QR drucken', copied: 'Link kopiert.', copyFailed: 'Kopieren nicht möglich. Link unten markieren und kopieren.',
    server: 'Servername in der Companion App (optional)', serverHelp: 'Leer lassen, um bei mehreren Servern die App-Auswahl zu verwenden.',
    qr: 'QR-Code für die Companion App', account: 'HA-Instanz', observed: 'Letzte Aktualisierung',
    neverStarted: 'Die Anfrage wurde nicht gestartet. Bitte eine neue Bestätigung anfordern.',
  },
  en: {
    title: 'Fabman', intro: 'Resource control', scan: 'Scan a resource QR code.',
    links: 'Enabled direct links', empty: 'No direct links enabled. Enable resources in Settings → Devices & services → Fabman → Configure → Direct links.',
    on: 'Turn machine on', off: 'Turn machine off', open: 'Open door',
    question: 'Do you want to perform this action?', cancel: 'Cancel',
    state: 'Observed state', active: 'ON', inactive: 'OFF', unknown: 'Unknown',
    door: 'Release state (not a door contact)', actor: 'You are starting usage as',
    api: 'Fabman API-key member', stop: 'The current machine usage will be stopped.',
    loading: 'Checking state …', sending: 'Preparing command …',
    accepted: 'Command accepted. Waiting for confirmation …',
    confirmed: 'Switching confirmed.', opened: 'Door release confirmed.',
    assigned: 'Member attribution confirmed.', assignmentPending: 'Checking member attribution …',
    attribution_unconfirmed: 'The command was accepted but member attribution could not be confirmed. Check the Fabman activity log.',
    timeout: 'Command sent but not confirmed. Check the state before trying again.',
    superseded: 'Another command replaced this operation. Check the current state.',
    rejected: 'Fabman rejected the command. Check permission, package and member mapping.',
    uncertain: 'The outcome is unknown. The resource may already have switched. Check its state and Fabman log before trying again.',
    interrupted: 'The integration reload interrupted this operation. The command may already have been sent. Check its state.',
    changed: 'State or attribution changed. Check again and confirm the new action.',
    expired: 'Confirmation or result expired. Check the current state before trying again.',
    unknown_state: 'Machine state is unknown. Switching is currently unavailable.',
    unavailable: 'This direct link or resource is currently unavailable.',
    unauthorized: 'You may not control this resource.', invalid_mapping: 'Your Fabman member mapping could not be verified.',
    busy: 'Too many open confirmations. Please try again later.',
    connection: 'Connection interrupted. No command will be resent.',
    check: 'Check again', status: 'Refresh status', cancelled: 'Cancelled.',
    browser: 'Copy browser link', app: 'Copy app link', download: 'Save QR as SVG',
    print: 'Print QR', copied: 'Link copied.', copyFailed: 'Copy failed. Select and copy the link below.',
    server: 'Server name in the Companion App (optional)', serverHelp: 'Leave empty to use the app server picker when several servers are configured.',
    qr: 'Companion App QR code', account: 'HA instance', observed: 'Last updated',
    neverStarted: 'This request was not started. Please request a new confirmation.',
  },
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function routeTarget(path) {
  const normalized = path.replace(/^\/fabman(?=\/|$)/, '');
  if (normalized === '' || normalized === '/') return null;
  const match = normalized.match(/^\/qr\/([A-Za-z0-9_-]+)\/([1-9][0-9]{0,9})\/?$/);
  if (!match || Number(match[2]) > 2147483647) throw new Error('unavailable');
  return {entry_id: match[1], resource_id: Number(match[2])};
}

export function appLink(path, server = '') {
  return `homeassistant://navigate${path}${server.trim() ? `?server=${encodeURIComponent(server.trim())}` : ''}`;
}

export function operationText(result, t) {
  const lines = [];
  if (result.error) lines.push(t[result.error] || t.uncertain);
  if (result.command_status === 'confirmed') lines.push(result.action === 'open' ? t.opened : t.confirmed);
  else if (result.command_status === 'timeout') lines.push(t.timeout);
  else if (result.command_status === 'superseded') lines.push(t.superseded);
  else if (result.command_status === 'unavailable' || result.command_status === 'unknown') lines.push(t.uncertain);
  else if (!result.error) lines.push(result.phase === 'running' ? t.sending : t.accepted);
  if (result.member_status === 'assigned') lines.push(t.assigned);
  if (result.member_status === 'pending') lines.push(t.assignmentPending);
  if (result.phase === 'prepared') return [t.neverStarted];
  return lines;
}

export class FabmanPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._revision = 0;
    this._server = '';
  }
  set hass(value) {
    this._hass = value;
    this._maybeLoad();
  }
  get hass() { return this._hass; }
  set route(value) { this._route = value; this._maybeLoad(); }
  set panel(value) { this._panel = value; }
  connectedCallback() { this._maybeLoad(); }
  disconnectedCallback() { clearTimeout(this._timer); this._loadedKey = null; this._revision++; }
  get t() { return TEXT[this._hass?.language?.startsWith('de') ? 'de' : 'en']; }
  _maybeLoad() {
    if (!this.isConnected || !this._hass?.user) return;
    const path = this._route?.path ?? window.location.pathname;
    const key = `${this._hass.user.id}:${path}`;
    if (key === this._loadedKey) return;
    this._loadedKey = key;
    this._load(path);
  }
  _call(type, data = {}) { return this._hass.callWS({type: `fabman/direct_link/${type}`, ...data}); }
  _stored(value) {
    try {
      if (value === undefined) return sessionStorage.getItem(this._storageKey);
      if (value === null) sessionStorage.removeItem(this._storageKey);
      else sessionStorage.setItem(this._storageKey, value);
    } catch { /* Storage may be disabled by the browser/app. */ }
    return null;
  }
  async _load(path) {
    const revision = ++this._revision;
    clearTimeout(this._timer);
    this._preview = null;
    this._operation = null;
    this._busy = false;
    this._error = null;
    this._links = null;
    this._result = null;
    this._target = null;
    this._notice = null;
    this.render();
    try {
      this._target = routeTarget(path);
      if (!this._target) {
        if (this._hass.user.is_admin) {
          const links = await this._call('list');
          if (revision === this._revision) { this._links = links; this.render(); }
        } else { this._notice = this.t.scan; this.render(); }
        return;
      }
      this._storageKey = `fabman-qr:${this._hass.user.id}:${this._target.entry_id}:${this._target.resource_id}`;
      const operation = this._stored();
      if (operation) {
        this._operation = operation;
        this._pollUntil = Date.now() + 120000;
        return await this._poll(revision);
      }
      const preview = await this._call('prepare', this._target);
      if (revision !== this._revision) return;
      this._preview = preview;
      this._expires = Date.now() + preview.expires_in * 1000;
      this.render();
      this._timer = setTimeout(() => {
        this._error = 'expired'; this._preview = null; this.render();
      }, preview.expires_in * 1000);
    } catch (error) {
      if (revision === this._revision) { this._error = error.code || error.message || 'connection'; this.render(); }
    }
  }
  async _execute() {
    if (this._busy || !this._preview) return;
    if (Date.now() >= this._expires) { this._error = 'expired'; this._preview = null; this.render(); return; }
    const revision = this._revision;
    this._busy = true;
    clearTimeout(this._timer);
    this._operation = this._preview.confirmation_id;
    // Persist before the send, so a lost response never causes an automatic retry.
    this._stored(this._operation);
    this.render();
    try {
      const result = await this._call('execute', {confirmation_id: this._operation});
      if (revision !== this._revision) return;
      this._result = result;
      this._preview = null;
      this._pollUntil = Date.now() + 120000;
      await this._poll(revision);
    } catch (error) {
      if (revision === this._revision) {
        this._preview = null; this._error = error.code || 'connection'; this.render();
      }
    }
  }
  async _poll(revision = this._revision) {
    clearTimeout(this._timer);
    try {
      const result = await this._call('status', {operation_id: this._operation});
      if (revision !== this._revision || !this.isConnected) return;
      this._error = null;
      this._result = result;
      const waiting = ['running', 'accepted'].includes(result.phase) && (result.phase === 'running' || result.command_status === 'pending' || result.member_status === 'pending');
      this._busy = waiting;
      this.render();
      if (waiting && Date.now() < this._pollUntil) this._timer = setTimeout(() => this._poll(revision), 1000);
      else if (waiting) { this._busy = false; this._error = 'uncertain'; this.render(); }
    } catch (error) {
      if (revision === this._revision) { this._busy = false; this._error = error.code || 'connection'; this.render(); }
    }
  }
  _button(label, action, primary = false) {
    const button = element('button', label, primary ? 'primary' : '');
    button.addEventListener('click', action);
    return button;
  }
  render() {
    const t = this.t;
    const style = element('style');
    style.textContent = `
      :host{display:block;color:var(--primary-text-color,#202b34);background:var(--primary-background-color,#f4f6f7);min-height:100%;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
      *{box-sizing:border-box}main{max-width:560px;margin:auto;padding:32px 20px 48px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}h1{font-size:20px;margin:0}h2{font-size:27px;line-height:1.25;margin:8px 0 22px;overflow-wrap:anywhere}.brand{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--secondary-text-color,#607080)}
      article{background:var(--card-background-color,white);border:1px solid var(--divider-color,#dce3e7);border-radius:20px;padding:28px;box-shadow:0 8px 32px #00000008;margin:18px 0}.badge{display:inline-block;background:var(--secondary-background-color,#eef3f5);border-radius:20px;padding:8px 12px;font-weight:600}.muted{color:var(--secondary-text-color,#607080);font-size:14px;line-height:1.6}.actor{padding:16px 0;border-top:1px solid var(--divider-color,#dce3e7);margin-top:24px}.actor strong{display:block;margin-top:6px;font-size:18px}p{line-height:1.6}button{display:block;min-height:48px;padding:12px 18px;margin:12px 0;width:100%;border:1px solid var(--divider-color,#dce3e7);border-radius:12px;color:inherit;background:transparent;font:inherit;cursor:pointer}button.primary{background:var(--primary-color,#087e8b);color:var(--text-primary-color,white);border-color:transparent;font-weight:650}button:disabled{opacity:.5;cursor:wait}.error{border-left:4px solid var(--error-color,#bd342d);padding-left:16px}.result{border-left:4px solid var(--primary-color,#087e8b);padding-left:16px}input{width:100%;padding:12px;margin-top:8px;font:inherit;border:1px solid var(--divider-color,#dce3e7);border-radius:8px;background:var(--card-background-color,white);color:inherit}.url{display:block;overflow-wrap:anywhere;font:12px/1.6 monospace;user-select:all}img{display:block;max-width:100%;width:264px;height:264px;margin:16px auto;background:white}button:focus-visible,input:focus-visible{outline:3px solid var(--primary-color,#087e8b);outline-offset:3px}@media(max-width:380px){main{padding:20px 12px}article{padding:20px}h2{font-size:24px}}`;
    const main = element('main');
    const header = element('header');
    header.append(element('h1', t.title), element('span', t.intro, 'brand'));
    main.append(header);
    if (this._notice) main.append(element('p', this._notice, 'muted'));
    if (this._error) main.append(element('p', t[this._error] || t.connection, 'error'));
    if (this._links !== null) this._renderLinks(main);
    else if (this._preview) this._renderPreview(main);
    else if (this._result) {
      const card = element('article');
      const result = element('div', undefined, 'result');
      result.setAttribute('role', 'status');
      for (const line of operationText(this._result, t)) result.append(element('p', line));
      card.append(result);
      main.append(card);
    } else if (!this._error && !this._notice) main.append(element('p', t.loading, 'muted'));
    if (this._operation) main.append(this._button(t.status, () => {
      this._pollUntil = Date.now() + 120000; this._poll();
    }));
    if ((this._error || this._result) && !this._busy && this._target) main.append(this._button(t.check, () => {
      this._stored(null); this._load(this._route?.path ?? window.location.pathname);
    }));
    this.shadowRoot.replaceChildren(style, main);
  }
  _renderPreview(main) {
    const p = this._preview, t = this.t;
    const card = element('article');
    card.append(element('span', `#${p.resource_id}`, 'brand'), element('h2', p.name));
    card.append(element('p', p.action === 'open' ? t.door : t.state, 'muted'));
    card.append(element('span', p.is_on === null ? t.unknown : p.is_on ? t.active : t.inactive, 'badge'));
    if (p.observed_at) card.append(element('p', `${t.observed}: ${new Date(p.observed_at).toLocaleString(this._hass.language)}`, 'muted'));
    const actor = element('div', undefined, 'actor');
    if (p.action === 'off') actor.append(element('p', t.stop));
    else actor.append(element('span', t.actor, 'muted'), element('strong', p.member_name || (p.member_id ? `Fabman #${p.member_id}` : t.api)));
    card.append(actor, element('p', t.question));
    const confirm = this._button(this._busy ? t.sending : t[p.action], () => this._execute(), true);
    confirm.disabled = this._busy;
    card.append(confirm);
    if (!this._busy) card.append(this._button(t.cancel, () => {
      clearTimeout(this._timer); this._preview = null; this._notice = t.cancelled; this.render();
    }));
    card.append(element('p', `${t.account}: ${window.location.host}`, 'muted'));
    main.append(card);
  }
  _renderLinks(main) {
    const t = this.t;
    main.append(element('h2', t.links));
    if (!this._links.length) main.append(element('p', t.empty, 'muted'));
    const label = element('label', t.server);
    const input = element('input'); input.value = this._server;
    input.addEventListener('change', () => { this._server = input.value; this.render(); });
    label.append(input); main.append(label, element('p', t.serverHelp, 'muted'));
    for (const link of this._links) {
      const card = element('article');
      const url = appLink(link.path, this._server);
      const qr = qrcode(0, 'M'); qr.addData(url); qr.make();
      const svg = qr.createSvgTag({cellSize: 4, margin: 16, scalable: true});
      const image = element('img'); image.alt = t.qr; image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
      card.append(element('span', link.entry_title, 'brand'), element('h2', link.name), image, element('code', url, 'url'));
      const copy = async (value) => {
        try { await navigator.clipboard.writeText(value); this._notice = t.copied; }
        catch { this._notice = t.copyFailed; }
        this.render();
      };
      const browser = new URL(link.path, window.location.origin).href;
      card.append(element('code', browser, 'url'));
      card.append(this._button(t.app, () => copy(url)), this._button(t.browser, () => copy(browser)));
      card.append(this._button(t.download, () => {
        const blob = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
        const anchor = element('a'); anchor.href = blob; anchor.download = 'fabman-qr.svg'; anchor.click();
        setTimeout(() => URL.revokeObjectURL(blob), 1000);
      }));
      card.append(this._button(t.print, () => {
        const popup = window.open('', '_blank');
        if (!popup) return;
        popup.opener = null;
        popup.document.title = link.name;
        const body = popup.document.body;
        body.style.cssText = 'font-family:system-ui;text-align:center;padding:32px;overflow-wrap:anywhere';
        const printImage = image.cloneNode(); printImage.style.cssText = 'width:320px;height:320px';
        printImage.onload = () => { popup.focus(); popup.print(); };
        body.append(element('h1', link.name), element('p', link.entry_title), printImage, element('p', url));
      }));
      main.append(card);
    }
  }
}

customElements.define('fabman-panel', FabmanPanel);
