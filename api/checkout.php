<?php
/*
 * Kommunradar – förifylld Stripe-kassa (körs på Simply.com, samma domän som sajten).
 *
 * Webbläsaren skickar vilken Payment Link besökaren klickade på plus bevakningsord, län och
 * e-post som redan angetts på sajten. Vi slår upp betallänken i Stripe och skapar en Checkout
 * Session med exakt samma pris, provperiod, villkor och tack-sida – men utan frågorna om
 * bevakningsord och län (de sparas i stället som metadata på prenumerationen, där digest.py läser
 * dem först) och med e-posten ifylld.
 *
 * Går något fel svarar vi med fel och webbläsaren skickar besökaren till den vanliga betallänken,
 * så ingen köpare tappas. Stripe-nyckeln ligger i en fil utanför public_html (skrivs av
 * workflowet checkout-prefill) och loggas aldrig.
 */
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, max-age=0');
header('X-Content-Type-Options: nosniff');

const KR_ALLOWED_HOSTS = ['kommunradar.online', 'www.kommunradar.online'];
const KR_COUNTIES = [
    'alla' => 'Hela Sverige', 'stockholm' => 'Stockholm', 'uppsala' => 'Uppsala',
    'sodermanland' => 'Södermanland', 'ostergotland' => 'Östergötland', 'orebro' => 'Örebro',
    'vastmanland' => 'Västmanland', 'jonkoping' => 'Jönköping', 'kronoberg' => 'Kronoberg',
    'kalmar' => 'Kalmar', 'gotland' => 'Gotland', 'blekinge' => 'Blekinge', 'skane' => 'Skåne',
    'halland' => 'Halland', 'vastragotaland' => 'Västra Götaland', 'varmland' => 'Värmland',
    'dalarna' => 'Dalarna', 'gavleborg' => 'Gävleborg', 'vasternorrland' => 'Västernorrland',
    'jamtland' => 'Jämtland', 'vasterbotten' => 'Västerbotten', 'norrbotten' => 'Norrbotten',
];

function kr_out(int $status, array $payload): void
{
    http_response_code($status);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function kr_key(): string
{
    $candidates = [
        dirname(__DIR__, 2) . '/kommunradar-private/stripe-key.php',
        __DIR__ . '/.stripe-key.php',
    ];
    foreach ($candidates as $file) {
        if (@is_readable($file)) {
            $key = trim((string) (include $file));
            if (preg_match('/^(sk|rk)_(live|test)_[A-Za-z0-9]+$/', $key)) {
                return $key;
            }
        }
    }
    return '';
}

/** "Västra Götaland", "vastragotaland", "Hela Sverige", "" → nyckel i KR_COUNTIES, eller null. */
function kr_county(string $raw): ?string
{
    $raw = trim($raw);
    if ($raw === '') {
        return null;
    }
    $fold = strtolower(strtr($raw, ['å' => 'a', 'ä' => 'a', 'ö' => 'o', 'Å' => 'a', 'Ä' => 'a', 'Ö' => 'o', 'é' => 'e', 'É' => 'e']));
    $fold = preg_replace('/[^a-z]/', '', $fold);
    if ($fold === 'helasverige' || $fold === 'sverige' || $fold === 'alla') {
        return 'alla';
    }
    $fold = preg_replace('/s?lan$/', '', $fold); // "Skåne län", "Stockholms län"
    return array_key_exists($fold, KR_COUNTIES) ? $fold : null;
}

/** "städ ; fönsterputs,städ" → "städ, fönsterputs" (max 8 ord, 2–60 tecken var). */
function kr_keywords(string $raw): string
{
    $raw = mb_substr($raw, 0, 300);
    $terms = [];
    foreach (preg_split('/[,;\n]+/u', $raw) as $term) {
        $term = trim(preg_replace('/[\p{C}]+/u', '', preg_replace('/\s+/u', ' ', $term)));
        $len = mb_strlen($term);
        if ($len < 2 || $len > 60) {
            continue;
        }
        $lower = mb_strtolower($term);
        if (!isset($terms[$lower])) {
            $terms[$lower] = $term;
        }
        if (count($terms) >= 8) {
            break;
        }
    }
    return implode(', ', $terms);
}

function kr_stripe(string $key, string $method, string $path, array $params = []): array
{
    $query = http_build_query($params, '', '&');
    $url = 'https://api.stripe.com/v1/' . $path . ($method === 'GET' && $query !== '' ? '?' . $query : '');
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 12,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $key, 'Stripe-Version: 2024-06-20'],
        CURLOPT_CUSTOMREQUEST => $method,
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

/** Hela betallänksobjektet för en buy.stripe.com-adress, bara Kommunradars egna och aktiva. */
function kr_payment_link(string $key, string $url): ?array
{
    $after = null;
    for ($page = 0; $page < 5; $page++) {
        $params = ['active' => 'true', 'limit' => 100];
        if ($after) {
            $params['starting_after'] = $after;
        }
        $list = kr_stripe($key, 'GET', 'payment_links', $params);
        foreach ($list['data'] as $link) {
            if (($link['url'] ?? '') === $url) {
                return (($link['metadata']['app'] ?? '') === 'kommunradar') ? $link : null;
            }
        }
        if (empty($list['has_more']) || !$list['data']) {
            return null;
        }
        $after = end($list['data'])['id'];
    }
    return null;
}

/** Platser kvar på en begränsad länk (grundarpris, Black Week): länkens egna köp + våra förifyllda köp. */
function kr_seats_left(string $key, array $link): bool
{
    $limit = $link['restrictions']['completed_sessions']['limit'] ?? null;
    if ($limit === null) {
        return true;
    }
    $used = (int) ($link['restrictions']['completed_sessions']['count'] ?? 0);
    $after = null;
    for ($page = 0; $page < 5; $page++) {
        $params = ['status' => 'complete', 'limit' => 100, 'created[gte]' => time() - 180 * 86400];
        if ($after) {
            $params['starting_after'] = $after;
        }
        $list = kr_stripe($key, 'GET', 'checkout/sessions', $params);
        foreach ($list['data'] as $s) {
            if (($s['metadata']['payment_link'] ?? '') === $link['id']) {
                $used++;
            }
        }
        if (empty($list['has_more']) || !$list['data']) {
            break;
        }
        $after = end($list['data'])['id'];
    }
    return $used < (int) $limit;
}

/** Stripe-parametrar för en Checkout Session som speglar betallänken, utan de frågor vi redan har svar på. */
function kr_session_params(array $link, array $items, array $values, string $cancelUrl): array
{
    $recurring = false;
    $p = ['locale' => 'sv'];
    foreach ($items as $i => $item) {
        $price = $item['price'] ?? [];
        $p["line_items[$i][price]"] = is_array($price) ? $price['id'] : $price;
        $p["line_items[$i][quantity]"] = (string) ($item['quantity'] ?? 1);
        $recurring = $recurring || !empty($price['recurring']);
    }
    $p['mode'] = $recurring ? 'subscription' : 'payment';

    $done = $link['after_completion']['redirect']['url'] ?? 'https://kommunradar.online/tack.html';
    $p['success_url'] = $done . (str_contains($done, '?') ? '&' : '?') . 'session_id={CHECKOUT_SESSION_ID}';
    $p['cancel_url'] = $cancelUrl;

    $p['billing_address_collection'] = ($link['billing_address_collection'] ?? 'auto') === 'required' ? 'required' : 'auto';
    if (!empty($link['allow_promotion_codes'])) {
        $p['allow_promotion_codes'] = 'true';
    }
    if (($link['consent_collection']['terms_of_service'] ?? 'none') === 'required') {
        $p['consent_collection[terms_of_service]'] = 'required';
    }
    if (!empty($link['tax_id_collection']['enabled'])) {
        $p['tax_id_collection[enabled]'] = 'true';
    }
    if (!empty($link['automatic_tax']['enabled'])) {
        $p['automatic_tax[enabled]'] = 'true';
    }
    $submit = $link['custom_text']['submit']['message'] ?? null;
    if ($submit) {
        $p['custom_text[submit][message]'] = $submit;
    }
    if ($recurring) {
        $p['payment_method_collection'] = ($link['payment_method_collection'] ?? 'always') === 'if_required' ? 'if_required' : 'always';
    } elseif (($link['customer_creation'] ?? '') === 'always') {
        $p['customer_creation'] = 'always';
    }
    if (!empty($values['email'])) {
        $p['customer_email'] = $values['email'];
    }

    // Frågor som besökaren redan svarat på tas bort; övriga (t.ex. län om bara sökord angetts) finns kvar.
    $n = 0;
    foreach ($link['custom_fields'] ?? [] as $f) {
        $key = $f['key'] ?? '';
        if (($key === 'bevakning' && $values['keywords'] !== '') || ($key === 'lan' && $values['lan'] !== null)) {
            continue;
        }
        $base = "custom_fields[$n]";
        $p["{$base}[key]"] = $key;
        $p["{$base}[type]"] = $f['type'];
        $p["{$base}[optional]"] = !empty($f['optional']) ? 'true' : 'false';
        $p["{$base}[label][type]"] = 'custom';
        $p["{$base}[label][custom]"] = $f['label']['custom'] ?? $key;
        if ($f['type'] === 'dropdown') {
            foreach ($f['dropdown']['options'] as $j => $opt) {
                $p["{$base}[dropdown][options][$j][label]"] = $opt['label'];
                $p["{$base}[dropdown][options][$j][value]"] = $opt['value'];
            }
        }
        $n++;
    }

    $meta = array_merge($link['metadata'] ?? [], ['app' => 'kommunradar', 'payment_link' => $link['id'], 'source' => 'prefilled-checkout']);
    if ($values['keywords'] !== '') {
        $meta['keywords'] = $values['keywords'];
    }
    if ($values['lan'] !== null) {
        $meta['lan'] = $values['lan'];
    }
    foreach ($meta as $k => $v) {
        $p["metadata[$k]"] = (string) $v;
    }
    if ($recurring) {
        $subMeta = array_merge($link['subscription_data']['metadata'] ?? [], array_intersect_key($meta, ['keywords' => 1, 'lan' => 1, 'app' => 1]));
        foreach ($subMeta as $k => $v) {
            $p["subscription_data[metadata][$k]"] = (string) $v;
        }
        $trial = $link['subscription_data']['trial_period_days'] ?? null;
        if ($trial) {
            $p['subscription_data[trial_period_days]'] = (string) $trial;
        }
    } else {
        foreach ($meta as $k => $v) {
            $p["payment_intent_data[metadata][$k]"] = (string) $v;
        }
    }
    return $p;
}

// ---------------------------------------------------------------------------------------------
if (PHP_SAPI === 'cli' && getenv('KR_CHECKOUT_LIB')) {
    return; // tester laddar bara funktionerna
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'GET' && isset($_GET['health'])) {
    kr_out(200, ['ok' => true, 'key' => kr_key() !== '', 'curl' => function_exists('curl_init')]);
}
if ($method !== 'POST') {
    header('Allow: POST');
    kr_out(405, ['error' => 'Använd POST.']);
}

$origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');
$host = strtolower((string) parse_url($origin, PHP_URL_HOST));
if ($origin !== '' && !in_array($host, KR_ALLOWED_HOSTS, true)) {
    kr_out(403, ['error' => 'Origin tillåts inte.']);
}

$raw = (string) file_get_contents('php://input', false, null, 0, 16384);
$in = json_decode($raw, true);
if (!is_array($in) || !empty($in['website'])) {
    kr_out(400, ['error' => 'Ogiltig förfrågan.']);
}

$linkUrl = (string) ($in['link'] ?? '');
if (!preg_match('#^https://buy\.stripe\.com/[A-Za-z0-9]+$#', $linkUrl)) {
    kr_out(400, ['error' => 'Okänd betallänk.']);
}
$email = trim((string) ($in['email'] ?? ''));
$values = [
    'keywords' => kr_keywords((string) ($in['keywords'] ?? '')),
    'lan' => kr_county((string) ($in['lan'] ?? '')),
    'email' => (filter_var($email, FILTER_VALIDATE_EMAIL) && strlen($email) <= 200) ? $email : '',
];
if ($values['keywords'] === '' && $values['lan'] === null && $values['email'] === '') {
    kr_out(422, ['error' => 'Inget att fylla i.']);
}

// Enkel spärr mot att någon spammar fram sessioner: högst 10 per IP och 10 minuter.
$ip = preg_replace('/[^0-9a-f.:]/i', '', (string) ($_SERVER['REMOTE_ADDR'] ?? ''));
$rateFile = sys_get_temp_dir() . '/krco_' . md5($ip);
$hits = array_filter(array_map('intval', @file($rateFile, FILE_IGNORE_NEW_LINES) ?: []), fn ($t) => $t > time() - 600);
if (count($hits) >= 10) {
    kr_out(429, ['error' => 'För många försök.']);
}
$hits[] = time();
@file_put_contents($rateFile, implode("\n", $hits));

$key = kr_key();
if ($key === '' || !function_exists('curl_init')) {
    kr_out(503, ['error' => 'Kassan är inte konfigurerad.']);
}

try {
    $link = kr_payment_link($key, $linkUrl);
    if (!$link) {
        kr_out(404, ['error' => 'Betallänken hittades inte.']);
    }
    if (!kr_seats_left($key, $link)) {
        kr_out(409, ['error' => 'Inga platser kvar.']);
    }
    $items = kr_stripe($key, 'GET', 'payment_links/' . rawurlencode($link['id']) . '/line_items', ['limit' => 20, 'expand[]' => 'data.price'])['data'];
    if (!$items) {
        kr_out(502, ['error' => 'Betallänken saknar pris.']);
    }
    $referer = (string) ($_SERVER['HTTP_REFERER'] ?? '');
    $cancel = in_array(strtolower((string) parse_url($referer, PHP_URL_HOST)), KR_ALLOWED_HOSTS, true)
        ? strtok($referer, '#') : 'https://kommunradar.online/';
    $session = kr_stripe($key, 'POST', 'checkout/sessions', kr_session_params($link, $items, $values, $cancel));
    $url = (string) ($session['url'] ?? '');
    if (!str_starts_with($url, 'https://checkout.stripe.com/')) {
        kr_out(502, ['error' => 'Stripe svarade konstigt.']);
    }
    kr_out(200, ['url' => $url]);
} catch (Throwable $e) {
    kr_out(502, ['error' => 'Stripe kunde inte nås.']);
}
