<?php
/*
 * Kommunradar – kundpanel på kommunradar.online/konto/ (Simply.com, ingen databas).
 *
 * Kunden anger sin e-post och får en engångslänk (inloggning utan lösenord). Länken bär en signerad
 * token: e-post + utgångstid + HMAC. Nyckeln till HMAC härleds från Stripe-nyckeln, så digest.py kan
 * lägga en färdig länk "Ändra din bevakning" i varje mejl utan någon ny hemlighet.
 *
 * På panelen ändrar kunden bevakningsord och län och pausar eller återupptar mejlen. Allt sparas som
 * metadata på kundens Kommunradar-prenumerationer i Stripe (keywords, lan, paused), där digest.py läser
 * det. "Hantera betalning" öppnar Stripes egen kundportal.
 *
 * Konfigurationen (Stripe-nyckel + SMTP för kundmejl) skrivs av workflowet kundpanel till en fil
 * utanför public_html och loggas aldrig.
 */
declare(strict_types=1);

const KP_SITE = 'https://kommunradar.online';
const KP_LOGIN_TTL = 86400;        // engångslänk från inloggningen: 1 dygn
const KP_COUNTIES = [
    'alla' => 'Hela Sverige', 'stockholm' => 'Stockholm', 'uppsala' => 'Uppsala',
    'sodermanland' => 'Södermanland', 'ostergotland' => 'Östergötland', 'orebro' => 'Örebro',
    'vastmanland' => 'Västmanland', 'jonkoping' => 'Jönköping', 'kronoberg' => 'Kronoberg',
    'kalmar' => 'Kalmar', 'gotland' => 'Gotland', 'blekinge' => 'Blekinge', 'skane' => 'Skåne',
    'halland' => 'Halland', 'vastragotaland' => 'Västra Götaland', 'varmland' => 'Värmland',
    'dalarna' => 'Dalarna', 'gavleborg' => 'Gävleborg', 'vasternorrland' => 'Västernorrland',
    'jamtland' => 'Jämtland', 'vasterbotten' => 'Västerbotten', 'norrbotten' => 'Norrbotten',
];

function kp_config(): array
{
    foreach ([dirname(__DIR__, 2) . '/kommunradar-private/panel-config.php', __DIR__ . '/.panel-config.php'] as $file) {
        if (@is_readable($file)) {
            $c = include $file;
            if (is_array($c) && preg_match('/^(sk|rk)_(live|test)_[A-Za-z0-9]+$/', (string) ($c['stripe'] ?? ''))) {
                return $c;
            }
        }
    }
    return [];
}

function kp_b64(string $s): string
{
    return rtrim(strtr(base64_encode($s), '+/', '-_'), '=');
}

function kp_unb64(string $s): string
{
    return (string) base64_decode(strtr($s, '-_', '+/'), true);
}

/** Samma nyckel som digest.panel_link(): HMAC-SHA256(nyckel = Stripe-nyckeln, "kommunradar-panel"). */
function kp_secret(string $stripeKey): string
{
    return hash_hmac('sha256', 'kommunradar-panel', $stripeKey, true);
}

function kp_token(string $email, int $exp, string $stripeKey): string
{
    $payload = strtolower($email) . '|' . $exp;
    return kp_b64($payload) . '.' . kp_b64(hash_hmac('sha256', $payload, kp_secret($stripeKey), true));
}

/** E-postadressen i en giltig token, annars null. */
function kp_verify(string $token, string $stripeKey, ?int $now = null): ?string
{
    $parts = explode('.', $token);
    if (count($parts) !== 2) {
        return null;
    }
    $payload = kp_unb64($parts[0]);
    $sig = kp_unb64($parts[1]);
    if ($payload === '' || !hash_equals(hash_hmac('sha256', $payload, kp_secret($stripeKey), true), $sig)) {
        return null;
    }
    [$email, $exp] = array_pad(explode('|', $payload, 2), 2, '0');
    return ((int) $exp >= ($now ?? time()) && filter_var($email, FILTER_VALIDATE_EMAIL)) ? $email : null;
}

function kp_keywords(string $raw): string
{
    $terms = [];
    foreach (preg_split('/[,;\n]+/u', mb_substr($raw, 0, 400)) as $term) {
        $term = trim(preg_replace('/[\p{C}]+/u', '', preg_replace('/\s+/u', ' ', $term)));
        $len = mb_strlen($term);
        if ($len >= 2 && $len <= 60 && !isset($terms[mb_strtolower($term)])) {
            $terms[mb_strtolower($term)] = $term;
        }
        if (count($terms) >= 10) {
            break;
        }
    }
    return implode(', ', $terms);
}

function kp_stripe(string $key, string $method, string $path, array $params = []): array
{
    $query = http_build_query($params, '', '&');
    $ch = curl_init('https://api.stripe.com/v1/' . $path . ($method === 'GET' && $query !== '' ? '?' . $query : ''));
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 12, CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $key, 'Stripe-Version: 2024-06-20'],
    ]);
    if ($method === 'POST') {
        curl_setopt($ch, CURLOPT_POSTFIELDS, $query);
    }
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $data = is_string($body) ? json_decode($body, true) : null;
    if ($status < 200 || $status >= 300 || !is_array($data)) {
        throw new RuntimeException('stripe ' . $status);
    }
    return $data;
}

/** Kundens aktiva Kommunradar-prenumerationer: [['sub' => …, 'customer' => cus_…], …]. */
function kp_subscriptions(string $key, string $email): array
{
    $out = [];
    $products = [];
    $found = kp_stripe($key, 'GET', 'customers/search', ['query' => "email:'" . str_replace("'", '', $email) . "'", 'limit' => 10])['data'];
    foreach ($found as $cus) {
        if (strcasecmp((string) ($cus['email'] ?? ''), $email) !== 0) {
            continue;
        }
        $subs = kp_stripe($key, 'GET', 'subscriptions', ['customer' => $cus['id'], 'status' => 'all', 'limit' => 20])['data'];
        foreach ($subs as $sub) {
            if (!in_array($sub['status'] ?? '', ['active', 'trialing', 'past_due'], true)) {
                continue;
            }
            $ours = false;
            foreach ($sub['items']['data'] ?? [] as $item) {
                $pid = (string) ($item['price']['product'] ?? '');
                if ($pid !== '' && !isset($products[$pid])) {
                    $p = kp_stripe($key, 'GET', 'products/' . rawurlencode($pid));
                    $products[$pid] = ($p['metadata']['app'] ?? '') === 'kommunradar' || stripos((string) ($p['name'] ?? ''), 'kommunradar') !== false;
                }
                $ours = $ours || ($products[$pid] ?? false);
            }
            if ($ours) {
                $out[] = ['sub' => $sub, 'customer' => $cus['id']];
            }
        }
    }
    return $out;
}

/** Nuvarande bevakning: metadata först, annars svaren från betalsidan (som digest.py). */
function kp_current(string $key, array $sub): array
{
    $meta = $sub['metadata'] ?? [];
    $kw = (string) ($meta['keywords'] ?? '');
    $lan = (string) ($meta['lan'] ?? '');
    if ($kw === '' || $lan === '') {
        $sessions = kp_stripe($key, 'GET', 'checkout/sessions', ['subscription' => $sub['id'], 'limit' => 1])['data'];
        foreach ($sessions[0]['custom_fields'] ?? [] as $f) {
            $v = (string) ($f['text']['value'] ?? $f['dropdown']['value'] ?? '');
            if (($f['key'] ?? '') === 'lan' && $lan === '') {
                $lan = $v;
            } elseif (($f['key'] ?? '') === 'bevakning' && $kw === '') {
                $kw = $v;
            }
        }
    }
    return [
        'keywords' => $kw,
        'lan' => isset(KP_COUNTIES[$lan]) ? $lan : 'alla',
        'paused' => ($meta['paused'] ?? '') === '1',
    ];
}

/** Minimal SMTP-klient (STARTTLS på 587 eller SSL på 465, AUTH LOGIN). Samma brevlåda som kundmejlen. */
function kp_mail(array $c, string $to, string $subject, string $text): void
{
    $port = (int) ($c['smtp_port'] ?: 587);
    $s = @stream_socket_client(($port === 465 ? 'ssl://' : 'tcp://') . $c['smtp_host'] . ':' . $port, $errno, $err, 20);
    if (!$s) {
        throw new RuntimeException('smtp connect');
    }
    stream_set_timeout($s, 20);
    $read = function () use ($s): string {
        $resp = '';
        while (($line = fgets($s, 515)) !== false) {
            $resp .= $line;
            if (strlen($line) < 4 || $line[3] !== '-') {
                break;
            }
        }
        return $resp;
    };
    $cmd = function (?string $line, string $expect) use ($s, $read): void {
        if ($line !== null) {
            fwrite($s, $line . "\r\n");
        }
        $resp = $read();
        if (strncmp($resp, $expect, strlen($expect)) !== 0) {
            throw new RuntimeException('smtp ' . substr($resp, 0, 3));
        }
    };
    $cmd(null, '220');
    $cmd('EHLO kommunradar.online', '250');
    if ($port !== 465) {
        $cmd('STARTTLS', '220');
        if (!stream_socket_enable_crypto($s, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)) {
            throw new RuntimeException('smtp tls');
        }
        $cmd('EHLO kommunradar.online', '250');
    }
    $cmd('AUTH LOGIN', '334');
    $cmd(base64_encode($c['smtp_user']), '334');
    $cmd(base64_encode($c['smtp_pass']), '235');
    $from = $c['mail_from'] ?: $c['smtp_user'];
    preg_match('/<([^>]+)>/', $from, $m);
    $cmd('MAIL FROM:<' . ($m[1] ?? $from) . '>', '250');
    $cmd('RCPT TO:<' . $to . '>', '250');
    $cmd('DATA', '354');
    $headers = [
        'From: ' . $from, 'To: <' . $to . '>', 'Reply-To: ' . ($c['reply_to'] ?: 'hej@kommunradar.online'),
        'Subject: =?UTF-8?B?' . base64_encode($subject) . '?=', 'Date: ' . date('r'),
        'Message-ID: <' . bin2hex(random_bytes(12)) . '@kommunradar.online>',
        'MIME-Version: 1.0', 'Content-Type: text/plain; charset=UTF-8', 'Content-Transfer-Encoding: base64',
    ];
    $cmd(implode("\r\n", $headers) . "\r\n\r\n" . chunk_split(base64_encode($text)) . '.', '250');
    fwrite($s, "QUIT\r\n");
    fclose($s);
}

function kp_json(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/** Högst $max anrop per nyckel och 10 minuter (filer i temp, ingen databas). */
function kp_limit(string $what, int $max): bool
{
    $file = sys_get_temp_dir() . '/krkp_' . md5($what);
    $hits = array_filter(array_map('intval', @file($file, FILE_IGNORE_NEW_LINES) ?: []), fn ($t) => $t > time() - 600);
    if (count($hits) >= $max) {
        return false;
    }
    $hits[] = time();
    @file_put_contents($file, implode("\n", $hits));
    return true;
}

// ---------------------------------------------------------------------------------------------
if (PHP_SAPI === 'cli' && getenv('KR_PANEL_LIB')) {
    return; // tester laddar bara funktionerna
}

header('Cache-Control: no-store, max-age=0');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
$config = kp_config();
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($method === 'GET' && isset($_GET['health'])) {
    kp_json(200, ['ok' => true, 'key' => isset($config['stripe']), 'smtp' => !empty($config['smtp_host']), 'curl' => function_exists('curl_init')]);
}

if ($method === 'POST') {
    $origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');
    if ($origin !== '' && !in_array(strtolower((string) parse_url($origin, PHP_URL_HOST)), ['kommunradar.online', 'www.kommunradar.online'], true)) {
        kp_json(403, ['error' => 'Origin tillåts inte.']);
    }
    if (!$config || !function_exists('curl_init')) {
        kp_json(503, ['error' => 'Panelen är inte igång just nu. Svara på valfritt mejl från oss så hjälper vi dig.']);
    }
    $in = json_decode((string) file_get_contents('php://input', false, null, 0, 16384), true);
    if (!is_array($in) || !empty($in['website'])) {
        kp_json(400, ['error' => 'Ogiltig förfrågan.']);
    }
    $key = $config['stripe'];
    $ip = preg_replace('/[^0-9a-f.:]/i', '', (string) ($_SERVER['REMOTE_ADDR'] ?? ''));
    $action = (string) ($in['action'] ?? '');

    try {
        if ($action === 'login') {
            $email = trim((string) ($in['email'] ?? ''));
            $sent = ['ok' => true, 'message' => 'Om adressen har en bevakning hos oss har vi skickat en inloggningslänk. Kolla inkorgen (och skräpposten).'];
            if (!filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($email) > 200) {
                kp_json(422, ['error' => 'Skriv en giltig e-postadress.']);
            }
            if (!kp_limit('ip' . $ip, 8) || !kp_limit('em' . strtolower($email), 3)) {
                kp_json(429, ['error' => 'För många försök. Vänta en stund och försök igen.']);
            }
            if (!kp_subscriptions($key, $email)) {
                kp_json(200, $sent); // avslöjar inte vilka adresser som är kunder
            }
            $link = KP_SITE . '/konto/?t=' . kp_token($email, time() + KP_LOGIN_TTL, $key);
            kp_mail($config, $email, 'Din inloggningslänk till Kommunradar',
                "Hej,\n\nHär är din länk för att ändra din bevakning hos Kommunradar:\n\n$link\n\n"
                . "Länken gäller i ett dygn. Har du inte bett om den kan du bortse från mejlet.\n\nKommunradar.online");
            kp_json(200, $sent);
        }

        $email = kp_verify((string) ($in['token'] ?? ''), $key);
        if ($email === null) {
            kp_json(401, ['error' => 'Länken har gått ut. Begär en ny nedan.']);
        }
        if (!kp_limit('tk' . $ip, 30)) {
            kp_json(429, ['error' => 'För många försök. Vänta en stund.']);
        }
        $subs = kp_subscriptions($key, $email);
        if (!$subs) {
            kp_json(404, ['error' => 'Vi hittar ingen aktiv bevakning för ' . $email . '.']);
        }

        if ($action === 'load') {
            $cur = kp_current($key, $subs[0]['sub']);
            kp_json(200, ['email' => $email, 'counties' => KP_COUNTIES] + $cur);
        }
        if ($action === 'save') {
            $kw = kp_keywords((string) ($in['keywords'] ?? ''));
            $lan = (string) ($in['lan'] ?? 'alla');
            if (!isset(KP_COUNTIES[$lan])) {
                kp_json(422, ['error' => 'Okänt län.']);
            }
            $paused = !empty($in['paused']);
            foreach ($subs as $s) {
                kp_stripe($key, 'POST', 'subscriptions/' . rawurlencode($s['sub']['id']), [
                    'metadata[keywords]' => $kw, 'metadata[lan]' => $lan, 'metadata[paused]' => $paused ? '1' : '',
                ]);
            }
            kp_json(200, ['ok' => true, 'keywords' => $kw, 'lan' => $lan, 'paused' => $paused,
                'message' => $paused ? 'Sparat. Mejlen är pausade tills du återupptar dem.' : 'Sparat. Ändringen gäller från nästa mejl.']);
        }
        if ($action === 'portal') {
            $portal = kp_stripe($key, 'POST', 'billing_portal/sessions', [
                'customer' => $subs[0]['customer'],
                'return_url' => KP_SITE . '/konto/?t=' . rawurlencode((string) $in['token']),
            ]);
            kp_json(200, ['url' => (string) ($portal['url'] ?? '')]);
        }
        kp_json(400, ['error' => 'Okänd åtgärd.']);
    } catch (Throwable $e) {
        kp_json(502, ['error' => 'Något gick fel just nu. Försök igen om en stund, eller svara på valfritt mejl från oss.']);
    }
}

header('Content-Type: text/html; charset=utf-8');
header("Content-Security-Policy: default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'");
?><!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Din bevakning · Kommunradar</title>
<link rel="icon" href="/favicon.svg">
<style>
  :root{--ink:#0b1020;--muted:#64748b;--line:#e2e8f0;--gold:#fbbf24;--bg:#f8fafc;--ok:#15803d;--err:#b91c1c}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
  header{background:var(--ink);color:#fff;padding:18px 16px}
  header a{color:#fff;text-decoration:none;font-weight:800;letter-spacing:.04em}
  main{max-width:560px;margin:28px auto;padding:0 16px}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px}
  h1{font-size:24px;margin:0 0 6px} p{line-height:1.5}
  label{display:block;font-weight:700;margin:16px 0 6px}
  input[type=email],textarea,select{width:100%;font:inherit;padding:11px 12px;border:1px solid #cbd5e1;border-radius:10px;background:#fff}
  textarea{min-height:84px;resize:vertical}
  .hint{color:var(--muted);font-size:14px;margin:6px 0 0}
  button{font:inherit;font-weight:800;border:0;border-radius:10px;padding:12px 18px;cursor:pointer;background:var(--ink);color:var(--gold)}
  button.ghost{background:#fff;color:var(--ink);border:1px solid #cbd5e1}
  button:disabled{opacity:.6;cursor:wait}
  .row{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}
  .switch{display:flex;gap:10px;align-items:center;margin-top:18px;font-weight:700}
  .msg{margin-top:14px;font-size:15px} .msg.ok{color:var(--ok)} .msg.err{color:var(--err)}
  .who{color:var(--muted);font-size:14px}
  .hp{position:absolute;left:-9999px}
  [hidden]{display:none!important}
</style>
</head>
<body>
<header><a href="/">KOMMUNRADAR</a></header>
<main>
  <section id="login" class="card">
    <h1>Ändra din bevakning</h1>
    <p>Skriv e-postadressen du får Kommunradar till, så mejlar vi en inloggningslänk. Inget lösenord behövs.</p>
    <form id="login-form">
      <label for="email">E-post</label>
      <input id="email" type="email" required autocomplete="email" placeholder="namn@foretag.se">
      <input class="hp" name="website" tabindex="-1" autocomplete="off">
      <div class="row"><button type="submit">Skicka inloggningslänk</button></div>
      <div id="login-msg" class="msg" role="status"></div>
    </form>
  </section>

  <section id="panel" class="card" hidden>
    <h1>Din bevakning</h1>
    <div class="who" id="who"></div>
    <form id="panel-form">
      <label for="keywords">Bevakningsord</label>
      <textarea id="keywords" placeholder="t.ex. lokalvård, fönsterputs, städentreprenad"></textarea>
      <p class="hint">Separera med komma. Använd ord som upphandlaren skriver. Lämna tomt för alla branscher.</p>
      <label for="lan">Län</label>
      <select id="lan"></select>
      <label class="switch"><input type="checkbox" id="paused"> Pausa mejlen</label>
      <p class="hint">Pausar bara utskicken. Betalningen påverkas inte, den hanterar du under "Hantera betalning".</p>
      <div class="row">
        <button type="submit">Spara</button>
        <button type="button" class="ghost" id="portal">Hantera betalning</button>
      </div>
      <div id="panel-msg" class="msg" role="status"></div>
    </form>
  </section>
  <p class="hint" style="text-align:center;margin-top:18px">Frågor? Svara på valfritt mejl från oss eller skriv till hej@kommunradar.online.</p>
</main>
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var token = new URLSearchParams(location.search).get('t') || '';
  function api(body) {
    return fetch('/konto/', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (d) { d._status = r.status; return d; }); })
      .catch(function () { return {error: 'Ingen kontakt. Kontrollera nätet och försök igen.'}; });
  }
  function say(el, d) { el.textContent = d.error || d.message || ''; el.className = 'msg ' + (d.error ? 'err' : 'ok'); }

  $('login-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var b = this.querySelector('button'); b.disabled = true;
    api({action: 'login', email: $('email').value, website: this.website.value}).then(function (d) { say($('login-msg'), d); b.disabled = false; });
  });

  function showLogin(d) { $('panel').hidden = true; $('login').hidden = false; if (d) say($('login-msg'), d); }

  if (token) {
    $('login').hidden = true;
    api({action: 'load', token: token}).then(function (d) {
      if (d.error) return showLogin(d);
      $('who').textContent = d.email;
      $('keywords').value = d.keywords || '';
      Object.keys(d.counties).forEach(function (k) {
        var o = document.createElement('option'); o.value = k; o.textContent = d.counties[k];
        if (k === d.lan) o.selected = true; $('lan').appendChild(o);
      });
      $('paused').checked = !!d.paused;
      $('panel').hidden = false;
    });
  }

  $('panel-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var b = this.querySelector('button[type=submit]'); b.disabled = true;
    api({action: 'save', token: token, keywords: $('keywords').value, lan: $('lan').value, paused: $('paused').checked})
      .then(function (d) { if (!d.error) $('keywords').value = d.keywords; say($('panel-msg'), d); b.disabled = false; });
  });

  $('portal').addEventListener('click', function () {
    var b = this; b.disabled = true;
    api({action: 'portal', token: token}).then(function (d) {
      if (d.url) { location.href = d.url; } else { say($('panel-msg'), d); b.disabled = false; }
    });
  });
})();
</script>
</body>
</html>
