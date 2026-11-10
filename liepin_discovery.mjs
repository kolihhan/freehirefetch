#!/usr/bin/env node
// Minimal GitHub-hosted Liepin discovery public source-only CN job discovery.
// The public endpoint, request shape, and defensive parsing were informed by
// rockbenben/ai-job-search-cn (MIT), especially its liepin-search CLI.

import fs from 'node:fs/promises';
import path from 'node:path';

export const SEARCH_URL = 'https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job';
const PAGE_SIZE = 40;

// Spread a 3-city x 6-query sweep over 9 short executions (4 requests/run),
// rather than making 36 consecutive requests that may trigger a rejected response.
const ROTATION_CITIES = ['上海', '深圳', '北京'];
const ROTATION_QUERY_PAIRS = [
  ['AI工程师', '大模型'],
  ['Agent', 'Python后端'],
  ['后端开发', '软件工程师'],
];
export function selectRotation(runNumber) {
  if (!Number.isInteger(runNumber) || runNumber <= 0) throw new Error('rotation number must be a positive integer');
  const slot = (runNumber - 1) % (ROTATION_CITIES.length * ROTATION_QUERY_PAIRS.length);
  return {
    slot,
    city: ROTATION_CITIES[Math.floor(slot / ROTATION_QUERY_PAIRS.length)],
    queries: ROTATION_QUERY_PAIRS[slot % ROTATION_QUERY_PAIRS.length],
    slotsPerSweep: ROTATION_CITIES.length * ROTATION_QUERY_PAIRS.length,
  };
}
const MIN_INTERVAL_MS = 1600;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

export const CITY_CODES = Object.freeze({
  北京: '010',
  上海: '020',
  天津: '030',
  广州: '050020',
  深圳: '050090',
  南京: '060020',
  杭州: '070020',
  合肥: '080020',
  福州: '090020',
  成都: '280020',
});

export function resolveCity(input) {
  const value = String(input ?? '').trim();
  if (!value) return null;
  if (/^\d{3,6}$/.test(value)) return value;
  const name = value.endsWith('市') ? value.slice(0, -1) : value;
  return CITY_CODES[name] ?? null;
}

export function buildSearchBody({ query, cityCode, page = 1 }) {
  return {
    data: {
      mainSearchPcConditionForm: {
        city: cityCode,
        dq: cityCode,
        pubTime: '',
        currentPage: Math.max(0, page - 1),
        pageSize: PAGE_SIZE,
        key: query,
        suggestTag: '',
        workYearCode: '0',
        compId: '',
        compName: '',
        compTag: '',
        industry: '',
        salary: '',
        jobKind: '',
        compScale: '',
        compKind: '',
        compStage: '',
        eduLevel: '',
      },
      passThroughForm: {
        scene: 'init',
        skeyword: query,
        sfrom: 'search_job_pc',
      },
    },
  };
}

function record(value) {
  return value && typeof value === 'object' ? value : {};
}

function nonEmptyString(value) {
  return typeof value === 'string' && value !== '' ? value : null;
}

function stringish(value) {
  if (typeof value === 'string') return value || null;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

function refreshTimeToDate(raw) {
  const value = stringish(raw);
  if (!value || value.length < 8) return null;
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

export function parseSearchResponse(payload) {
  const root = record(payload);
  if (root.flag !== 1) throw new Error(`Liepin response flag=${String(root.flag)}`);

  const data = record(root.data);
  const pagination = record(data.pagination);
  if (typeof pagination.totalPage !== 'number') throw new Error('Liepin response missing pagination');

  const inner = record(data.data);
  const rawCards = Array.isArray(inner.jobCardList) ? inner.jobCardList : [];
  const jobs = [];
  let skipped = 0;

  for (const raw of rawCards) {
    const card = record(raw);
    const job = record(card.job);
    const comp = record(card.comp);
    const recruiter = record(card.recruiter);
    const sourceId = stringish(job.jobId);
    const title = nonEmptyString(job.title);
    const url = nonEmptyString(job.link);
    if (!sourceId || !title || !url) {
      skipped += 1;
      continue;
    }
    jobs.push({
      source: 'liepin',
      sourceId,
      title,
      company: nonEmptyString(comp.compName),
      location: nonEmptyString(job.dq),
      salary: nonEmptyString(job.salary),
      date: refreshTimeToDate(job.refreshTime),
      url,
      education: nonEmptyString(job.requireEduLevel),
      experience: nonEmptyString(job.requireWorkYears),
      companyScale: nonEmptyString(comp.compScale),
      industry: nonEmptyString(comp.compIndustry),
      companyStage: nonEmptyString(comp.compStage),
      recruiterTitle: nonEmptyString(recruiter.recruiterTitle),
      isHeadhunter: stringish(job.jobKind) === '1',
    });
  }

  if (rawCards.length > 0 && jobs.length === 0) {
    throw new Error(`Liepin returned ${rawCards.length} cards but none parsed`);
  }

  return {
    jobs,
    skipped,
    currentPage: Number(pagination.currentPage ?? 0),
    totalPage: pagination.totalPage,
    totalCounts: Number(pagination.totalCounts ?? 0),
  };
}

function beijingDate(ms) {
  return new Date(ms + 8 * 3600_000).toISOString().slice(0, 10);
}

export function filterRecent(jobs, days, nowMs = Date.now()) {
  if (!days || days <= 0) return { jobs, droppedTooOld: 0, droppedNoDate: 0 };
  const cutoff = beijingDate(nowMs - days * 86400_000);
  let droppedTooOld = 0;
  let droppedNoDate = 0;
  const kept = jobs.filter((job) => {
    if (!job.date) {
      droppedNoDate += 1;
      return false;
    }
    if (job.date < cutoff) {
      droppedTooOld += 1;
      return false;
    }
    return true;
  });
  return { jobs: kept, droppedTooOld, droppedNoDate };
}

export function dedupeJobs(jobs) {
  const seen = new Set();
  const out = [];
  for (const job of jobs) {
    const key = `${job.source ?? 'liepin'}:${job.sourceId ?? job.url ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(job);
  }
  return out;
}

let lastRequestAt = 0;
async function throttle() {
  const wait = MIN_INTERVAL_MS - (Date.now() - lastRequestAt);
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  lastRequestAt = Date.now();
}

export async function fetchSearch(body, { fetchImpl = fetch, maxRetries = 3 } = {}) {
  let delay = 800;
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    await throttle();
    let response;
    try {
      response = await fetchImpl(SEARCH_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Origin: 'https://www.liepin.com',
          Referer: 'https://www.liepin.com/',
          'User-Agent': UA,
          'X-Client-Type': 'web',
          'X-Fscp-Version': '1.1',
          'X-Requested-With': 'XMLHttpRequest',
          'X-Fscp-Std-Info': '{"client_id": "40108"}',
          'X-Fscp-Trace-Id': crypto.randomUUID(),
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(15000),
      });
    } catch (error) {
      if (attempt === maxRetries) throw error;
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 8000);
      continue;
    }

    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) throw new Error(`Liepin rate limited/service error: HTTP ${response.status}`);
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, 8000);
      continue;
    }
    if (!response.ok) throw new Error(`Liepin request failed: HTTP ${response.status}`);

    const text = await response.text();
    if (text.trimStart().startsWith('<')) throw new Error('Liepin returned HTML instead of JSON (likely anti-bot challenge)');
    return JSON.parse(text);
  }
  throw new Error('Liepin retries exhausted');
}

function parseArgs(argv) {
  const args = { queries: [], cities: [], pages: 1, days: 0, output: 'artifacts/liepin-raw.json', rotationNumber: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const value = argv[i + 1];
    if (arg === '--query') { args.queries.push(value); i += 1; }
    else if (arg === '--city') { args.cities.push(value); i += 1; }
    else if (arg === '--pages') { args.pages = Number(value); i += 1; }
    else if (arg === '--rotation-number') { args.rotationNumber = Number(value); i += 1; }
    else if (arg === '--days') { args.days = Number(value); i += 1; }
    else if (arg === '--output') { args.output = value; i += 1; }
    else if (arg === '--help') { args.help = true; }
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function usage() {
  return `Usage: node scripts/liepin_discovery.mjs --city 上海 --query AI工程师 [options]\n\n` +
    `Repeat --city/--query, or pass --rotation-number N for the bounded 9-slot official sweep. Options: --pages N --days N --output PATH`;
}

export async function runDiscovery(options) {
  const searches = [];
  const allJobs = [];
  let totalSkipped = 0;
  let totalOld = 0;
  let totalNoDate = 0;
  const failedPages = [];
  let completedQueryCount = 0;

  for (const city of options.cities) {
    const cityCode = resolveCity(city);
    if (!cityCode) throw new Error(`Unsupported city: ${city}`);
    for (const query of options.queries) {
      let queryCompleted = false;
      for (let page = 1; page <= options.pages; page += 1) {
        let parsed;
        try {
          const payload = await fetchSearch(buildSearchBody({ query, cityCode, page }));
          parsed = parseSearchResponse(payload);
        } catch (error) {
          failedPages.push({ city, query, page, reason: String(error?.message ?? error).slice(0, 180) });
          break; // Preserve prior successful pages and continue with the next query.
        }
        const recent = filterRecent(parsed.jobs, options.days);
        totalSkipped += parsed.skipped;
        totalOld += recent.droppedTooOld;
        totalNoDate += recent.droppedNoDate;
        allJobs.push(...recent.jobs);
        searches.push({ city, cityCode, query, page, count: recent.jobs.length, totalPage: parsed.totalPage, skipped: parsed.skipped });
        if (page >= parsed.totalPage || page >= options.pages) {
          queryCompleted = true;
          break;
        }
      }
      if (queryCompleted) completedQueryCount += 1;
    }
  }

  const deduped = dedupeJobs(allJobs);
  return {
    generatedAt: new Date().toISOString(),
    source: 'liepin-public-api',
    policy: { publicSourceOnly: true, loginRequired: false, requestIntervalMs: MIN_INTERVAL_MS },
    meta: {
      searchCount: searches.length,
      rawAfterAgeFilter: allJobs.length,
      uniqueJobs: deduped.length,
      duplicatesRemoved: allJobs.length - deduped.length,
      skippedMalformed: totalSkipped,
      droppedTooOld: totalOld,
      droppedNoDate: totalNoDate,
      requestedQueryCount: options.cities.length * options.queries.length,
      completedQueryCount,
      failedPageCount: failedPages.length,
      runQuality: failedPages.length ? 'PARTIAL_COVERAGE' : 'SOURCE_SAMPLE_COMPLETED',
    },
    failedPages,
    searches,
    jobs: deduped,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  if (args.rotationNumber !== null) {
    if (args.cities.length || args.queries.length) throw new Error('--rotation-number cannot be combined with explicit --city/--query');
    const selected = selectRotation(args.rotationNumber);
    args.cities = [selected.city];
    args.queries = selected.queries;
    console.log('Liepin bounded rotation: ' + JSON.stringify(selected));
  }
  if (args.queries.length === 0 || args.cities.length === 0) {
    throw new Error('At least one --query and one --city are required');
  }
  if (!Number.isInteger(args.pages) || args.pages < 1 || args.pages > 3) throw new Error('--pages must be an integer from 1 to 3');
  if (!Number.isInteger(args.days) || args.days < 0 || args.days > 365) throw new Error('--days must be an integer from 0 to 365');

  const result = await runDiscovery(args);
  await fs.mkdir(path.dirname(args.output), { recursive: true });
  await fs.writeFile(args.output, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(`Liepin discovery: ${result.meta.uniqueJobs} unique jobs from ${result.meta.searchCount} searches -> ${args.output}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
