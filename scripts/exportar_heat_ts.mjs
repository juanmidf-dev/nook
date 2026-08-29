/**
 * Ejecuta el motor de calor del navegador y guarda su resultado.
 *
 * Existe para que `pipelines/tests/test_heat.py` pueda comprobar que
 * `src/lib/heat.ts` y `pipelines/nook/heat.py` dan el mismo número. Esa
 * equivalencia es un requisito del proyecto —el mapa la calcula en el
 * navegador y los informes en PDF en Python— y hasta ahora no la verificaba
 * nada. De hecho ya se habían separado: la versión de Python tiene un término
 * de población que la de TypeScript no implementa.
 *
 * Se transpila con esbuild, que ya viene con Vite, en vez de añadir una
 * dependencia nueva solo para esto.
 *
 *     node scripts/exportar_heat_ts.mjs
 */

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DESTINO = path.join(RAIZ, 'pipelines', 'tests', 'fixtures', 'heat_ts.json');

// Un caso pequeño y fijo, no los datos reales de un municipio: lo que se
// compara es el modelo, y con 12 puntos el fallo se localiza; con 320, no.
const PUNTOS = [
  { id: 'n1', categoria: 'notaria', nombre: 'Notaría 1', lat: 41.5431, lon: 2.1097 },
  { id: 'n2', categoria: 'notaria', nombre: 'Notaría 2', lat: 41.5480, lon: 2.1050 },
  { id: 'b1', categoria: 'banco', nombre: 'Banco 1', lat: 41.5440, lon: 2.1100 },
  { id: 'b2', categoria: 'banco', nombre: 'Banco 2', lat: 41.5400, lon: 2.1150 },
  { id: 'b3', categoria: 'banco', nombre: 'Banco 3', lat: 41.5500, lon: 2.1000 },
  { id: 'i1', categoria: 'inmobiliaria', nombre: 'Inmo 1', lat: 41.5450, lon: 2.1120 },
  { id: 'i2', categoria: 'inmobiliaria', nombre: 'Inmo 2', lat: 41.5380, lon: 2.1060 },
  { id: 'i3', categoria: 'inmobiliaria', nombre: 'Inmo 3', lat: 41.5520, lon: 2.1180 },
  { id: 'a1', categoria: 'abogados', nombre: 'Abogados 1', lat: 41.5460, lon: 2.1030 },
  { id: 'a2', categoria: 'abogados', nombre: 'Abogados 2', lat: 41.5410, lon: 2.1200 },
  { id: 'g1', categoria: 'gestoria', nombre: 'Gestoría 1', lat: 41.5470, lon: 2.1090 },
  { id: 'g2', categoria: 'gestoria', nombre: 'Gestoría 2', lat: 41.5390, lon: 2.1010 },
];

const CENTRO = [2.1097, 41.5431];
const RADIO_M = 2000;

// Varias configuraciones: una sola no distingue un motor correcto de uno que
// ignora los parámetros.
const CONFIGS = [
  { nombre: 'por-defecto', resolucion: 9, bandwidthM: 600, pesos: { banco: 1, inmobiliaria: 1, abogados: 1, gestoria: 1 }, pesoCompetencia: 0.7 },
  { nombre: 'sin-competencia', resolucion: 9, bandwidthM: 600, pesos: { banco: 1, inmobiliaria: 1, abogados: 1, gestoria: 1 }, pesoCompetencia: 0 },
  { nombre: 'competencia-total', resolucion: 9, bandwidthM: 600, pesos: { banco: 1, inmobiliaria: 1, abogados: 1, gestoria: 1 }, pesoCompetencia: 1 },
  { nombre: 'pesos-dispares', resolucion: 9, bandwidthM: 400, pesos: { banco: 2, inmobiliaria: 0.5, abogados: 1.5, gestoria: 3 }, pesoCompetencia: 0.5 },
  { nombre: 'rejilla-fina', resolucion: 10, bandwidthM: 300, pesos: { banco: 1, inmobiliaria: 1, abogados: 1, gestoria: 1 }, pesoCompetencia: 0.7 },
];

const tmp = mkdtempSync(path.join(tmpdir(), 'nook-heat-'));
try {
  const bundle = path.join(tmp, 'heat.mjs');
  execFileSync(
    'npx',
    ['esbuild', path.join(RAIZ, 'src/lib/heat.ts'), '--bundle', '--format=esm',
     '--platform=node', `--outfile=${bundle}`, '--log-level=warning'],
    { cwd: RAIZ, stdio: 'inherit', shell: process.platform === 'win32' },
  );

  const { bboxDeCentro, calcular, celdasDeBBox } = await import(pathToFileURL(bundle).href);

  const salida = { puntos: PUNTOS, centro: CENTRO, radioM: RADIO_M, casos: {} };
  for (const { nombre, ...cfg } of CONFIGS) {
    const celdas = celdasDeBBox(bboxDeCentro(CENTRO, RADIO_M), cfg.resolucion);
    const r = calcular(celdas, PUNTOS, cfg);
    salida.casos[nombre] = {
      config: cfg,
      celdas: Object.fromEntries(
        r.map((c) => [c.h3, { demanda: c.demanda, competencia: c.competencia, score: c.score }]),
      ),
    };
    console.log(`${nombre}: ${r.length} celdas`);
  }

  writeFileSync(DESTINO, JSON.stringify(salida, null, 1) + '\n', 'utf-8');
  console.log('->', path.relative(RAIZ, DESTINO));
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
