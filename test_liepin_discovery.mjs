import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildSearchBody,
  parseSearchResponse,
  filterRecent,
  dedupeJobs,
  resolveCity,
  selectRotation,
} from './liepin_discovery.mjs';

test('resolveCity maps supported Chinese city names and numeric codes', () => {
  assert.equal(resolveCity('上海'), '020');
  assert.equal(resolveCity('深圳市'), '050090');
  assert.equal(resolveCity('010'), '010');
  assert.equal(resolveCity('未知城市'), null);
});

test('buildSearchBody encodes query, city and zero-based page', () => {
  const body = buildSearchBody({ query: 'AI Engineer', cityCode: '020', page: 2 });
  const form = body.data.mainSearchPcConditionForm;
  assert.equal(form.city, '020');
  assert.equal(form.dq, '020');
  assert.equal(form.key, 'AI Engineer');
  assert.equal(form.currentPage, 1);
  assert.equal(form.pageSize, 40);
});

test('parseSearchResponse normalizes valid cards and skips malformed cards', () => {
  const payload = {
    flag: 1,
    data: {
      pagination: { currentPage: 0, totalPage: 3, totalCounts: 120 },
      data: {
        jobCardList: [
          {
            job: {
              jobId: 12345,
              title: 'AI 工程师',
              link: 'https://www.liepin.com/job/12345.shtml',
              dq: '上海',
              salary: '20-35k·14薪',
              refreshTime: 20261009103000,
              requireEduLevel: '硕士',
              requireWorkYears: '1-3年',
              jobKind: 0,
            },
            comp: {
              compName: '示例科技',
              compScale: '100-499人',
              compIndustry: '互联网',
              compStage: 'B轮',
            },
            recruiter: { recruiterTitle: 'HRBP', recruiterName: '王女士' },
          },
          { job: { jobId: 'bad', title: '', link: '' }, comp: {}, recruiter: {} },
        ],
      },
    },
  };

  const parsed = parseSearchResponse(payload);
  assert.equal(parsed.jobs.length, 1);
  assert.equal(parsed.skipped, 1);
  assert.equal(parsed.totalPage, 3);
  assert.deepEqual(parsed.jobs[0], {
    source: 'liepin',
    sourceId: '12345',
    title: 'AI 工程师',
    company: '示例科技',
    location: '上海',
    salary: '20-35k·14薪',
    date: '2026-10-09',
    url: 'https://www.liepin.com/job/12345.shtml',
    education: '硕士',
    experience: '1-3年',
    companyScale: '100-499人',
    industry: '互联网',
    companyStage: 'B轮',
    recruiterTitle: 'HRBP',
    isHeadhunter: false,
  });
});

test('parseSearchResponse rejects malformed top-level responses instead of reporting zero jobs', () => {
  assert.throws(() => parseSearchResponse({ flag: 0 }), /flag=0/);
  assert.throws(() => parseSearchResponse({ flag: 1, data: {} }), /pagination/);
});

test('filterRecent keeps jobs inside the age window and reports undated/old drops', () => {
  const jobs = [
    { sourceId: 'a', date: '2026-10-09' },
    { sourceId: 'b', date: '2026-10-05' },
    { sourceId: 'c', date: null },
  ];
  const out = filterRecent(jobs, 3, Date.parse('2026-10-09T12:00:00+08:00'));
  assert.deepEqual(out.jobs.map((j) => j.sourceId), ['a']);
  assert.equal(out.droppedTooOld, 1);
  assert.equal(out.droppedNoDate, 1);
});

test('dedupeJobs removes duplicate source ids while preserving first occurrence', () => {
  const jobs = [
    { source: 'liepin', sourceId: '1', title: 'first' },
    { source: 'liepin', sourceId: '1', title: 'duplicate' },
    { source: 'liepin', sourceId: '2', title: 'second' },
  ];
  assert.deepEqual(dedupeJobs(jobs).map((j) => j.title), ['first', 'second']);
});

test('bounded rotation covers all three cities and six queries in nine slots', () => {
  const slots = Array.from({ length: 9 }, (_, i) => selectRotation(i + 1));
  const pairs = slots.flatMap(s => s.queries.map(q => `${s.city}:${q}`));
  assert.equal(new Set(pairs).size, 18);
  assert.deepEqual(selectRotation(1), {slot: 0, city: '上海', queries: ['AI工程师', '大模型'], slotsPerSweep: 9});
  assert.deepEqual(selectRotation(10), selectRotation(1));
  assert.deepEqual(selectRotation(9).city, '北京');
  assert.throws(() => selectRotation(0), /positive integer/);
});
