// Load test of the API against the SLOs in docs/operations/slo.md:
//   p95 < 500 ms, p99 < 1 s, server errors < 0.1 %.
//
// Traffic mix modelled on a working day: mostly reading (dashboard, lists, searches), some order entry.
// Users come from loadtest/prepare.py (one token per virtual user group, so per-user limits behave
// like real traffic). Run from inside the Docker network against the API service:
//
//   docker run --rm --network sims_app -v "$PWD/loadtest:/loadtest" grafana/k6:2.3.0 run \
//     -e BASE_URL=http://backend:8000 /loadtest/k6/api-load.js
import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const data = JSON.parse(open('../.data/k6-data.json'));
const BASE = `${__ENV.BASE_URL || 'http://backend:8000'}/api/v1`;

const serverErrors = new Rate('server_errors');
const orderLatency = new Trend('order_create_ms', true);

export const options = {
  scenarios: {
    browse: {
      executor: 'ramping-vus',
      exec: 'browse',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 30 },
        { duration: '2m', target: 30 },
        { duration: '20s', target: 0 },
      ],
    },
    order_entry: {
      executor: 'constant-arrival-rate',
      exec: 'createOrder',
      rate: 2, // orders per second, sustained
      timeUnit: '1s',
      duration: '2m30s',
      preAllocatedVUs: 10,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    server_errors: ['rate<0.001'],
    checks: ['rate>0.999'],
    order_create_ms: ['p(95)<800'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const headers = () => ({
  Authorization: `Bearer ${data.tokens[(__VU - 1) % data.tokens.length]}`,
  'Content-Type': 'application/json',
});

function record(res, name) {
  serverErrors.add(res.status >= 500);
  check(res, { [`${name} ok`]: (r) => r.status >= 200 && r.status < 300 });
}

const SEARCHES = ['lap', 'mon', 'load', 'k', 'usb', 'ssd'];

export function browse() {
  const h = { headers: headers() };
  group('dashboard', () => {
    record(http.get(`${BASE}/dashboard/summary`, h), 'summary');
    record(http.get(`${BASE}/dashboard/sales-trend?days=60`, h), 'trend');
    record(http.get(`${BASE}/dashboard/top-products?limit=5&days=30`, h), 'top products');
  });
  sleep(1);
  group('lists', () => {
    const term = SEARCHES[Math.floor(Math.random() * SEARCHES.length)];
    record(http.get(`${BASE}/products?search=${term}&page_size=20`, h), 'product search');
    record(http.get(`${BASE}/orders?page_size=20`, h), 'orders');
    record(http.get(`${BASE}/customers?page_size=20`, h), 'customers');
  });
  sleep(1 + Math.random());
}

export function createOrder() {
  const body = JSON.stringify({
    customer_id: data.customer_id,
    items: [{ product_id: data.product_id, quantity: 1 + Math.floor(Math.random() * 3) }],
  });
  const params = {
    headers: { ...headers(), 'Idempotency-Key': `load-${__VU}-${__ITER}-${Date.now()}` },
  };
  const res = http.post(`${BASE}/orders`, body, params);
  orderLatency.add(res.timings.duration);
  record(res, 'order created');
}
