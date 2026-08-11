import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

import { buildSlide01 } from "./grid/slide-01.mjs";
import { buildSlide05 } from "./grid/slide-05.mjs";
import { buildSlide06 } from "./grid/slide-06.mjs";
import { buildSlide09 } from "./grid/slide-09.mjs";
import { buildSlide11 } from "./grid/slide-11.mjs";
import { buildSlide13 } from "./grid/slide-13.mjs";
import { buildSlide16 } from "./grid/slide-16.mjs";
import { buildSlide17 } from "./grid/slide-17.mjs";
import { buildSlide18 } from "./grid/slide-18.mjs";
import { buildSlide19 } from "./grid/slide-19.mjs";
import { buildSlide26 } from "./grid/slide-26.mjs";

const FINAL_PPTX = "C:/Users/goodd/Documents/Git Repository/UOSLabManager/UOSLabManager_프로그램_분석_및_개선_로드맵.pptx";
const OUTPUT_DIR = "C:/Users/goodd/Documents/Git Repository/UOSLabManager/tmp/ppt_uoslabmanager_20260810/render_api";

const COLORS = {
  ink: "#000000",
  muted: "#475569",
  panel: "#F2F2F2",
  rule: "#B8BCC4",
  accent: "#6DCBF4",
  accentStrong: "#3D8DFF",
  pale: "#EAF5FB",
  warning: "#F59E0B",
  danger: "#DC2626",
  success: "#16A34A",
  white: "#FFFFFF",
};

const FONT = "Malgun Gothic";

function para(text, fontSize = 21.33, options = {}) {
  return {
    runs: [{
      run: text,
      textStyle: {
        fontSize: `${fontSize}px`,
        typeface: FONT,
        color: options.color || COLORS.ink,
        bold: Boolean(options.bold),
      },
    }],
    spaceAfter: options.spaceAfter ?? 520,
    paragraphStyle: { lineSpacingPercent: options.lineSpacingPercent ?? 112000 },
  };
}

function pair(title, body, bodySize = 19) {
  return {
    titleHere: para(title, 27, { bold: true, spaceAfter: 520 }),
    loremIpsumDolorSitAmetConsecteturAdipiscing: para(body, bodySize, {
      color: COLORS.muted,
      spaceAfter: 0,
      lineSpacingPercent: 118000,
    }),
  };
}

function point(title, body, bodySize = 18.5) {
  return {
    titleGoesHere: para(title, 25, { bold: true, spaceAfter: 450 }),
    loremIpsumDolorSitAmetConsecteturAdipiscing: para(body, bodySize, {
      color: COLORS.muted,
      spaceAfter: 0,
      lineSpacingPercent: 116000,
    }),
  };
}

function notes(slide, sourceLines, presenter = "") {
  const body = [
    presenter,
    "[Sources]",
    ...sourceLines.map((line) => `- ${line}`),
  ].filter(Boolean).join("\n");
  slide.speakerNotes.textFrame.setText(body);
  slide.speakerNotes.setVisible(true);
}

function addText(slide, name, text, position, fontSize = 22, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize,
    typeface: FONT,
    color: options.color || COLORS.ink,
    bold: Boolean(options.bold),
    alignment: options.alignment || "left",
    verticalAlignment: options.verticalAlignment || "top",
    autoFit: options.autoFit || "shrinkText",
    insets: options.insets || { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addNode(slide, name, title, subtitle, position, options = {}) {
  const node = slide.shapes.add({
    geometry: "roundRect",
    name,
    position,
    fill: options.fill || COLORS.panel,
    line: { style: "solid", fill: options.line || COLORS.rule, width: 1 },
    borderRadius: "rounded-xl",
  });
  addText(
    slide,
    `${name}-title`,
    title,
    { left: position.left + 20, top: position.top + 15, width: position.width - 40, height: 28 },
    21,
    { bold: true, color: options.titleColor || COLORS.ink },
  );
  addText(
    slide,
    `${name}-subtitle`,
    subtitle,
    { left: position.left + 20, top: position.top + 47, width: position.width - 40, height: position.height - 58 },
    15.5,
    { color: options.subtitleColor || COLORS.muted },
  );
  return node;
}

function addVerticalConnector(slide, name, x, y, h) {
  slide.shapes.add({
    geometry: "straightConnector1",
    name,
    position: { left: x, top: y, width: 0, height: h },
    fill: "none",
    line: { style: "solid", fill: COLORS.accentStrong, width: 2 },
  });
}

function addSectionMark(slide, label) {
  addText(slide, `section-${label}`, label, { left: 1008, top: 64, width: 210, height: 30 }, 13.5, {
    color: COLORS.accentStrong,
    bold: true,
    alignment: "right",
  });
}

function buildCompetitorSlide(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = COLORS.white;
  addText(slide, "competitor-title", "범용 계측 기능만으로는 차별화하기 어렵다", { left: 41.33, top: 36.12, width: 1000, height: 64 }, 38.67, { bold: true });
  addText(slide, "competitor-subtitle", "기존 도구가 이미 잘하는 영역을 복제하기보다, 현재 자산이 모이는 지점을 제품의 중심으로 삼아야 합니다.", { left: 42, top: 111, width: 1160, height: 72 }, 20, { color: COLORS.muted });

  const values = [
    ["도구", "이미 강한 영역", "정면 경쟁을 피할 영역", "UOSLabManager의 기회"],
    ["LabVIEW", "그래픽 개발·장비 연결·배포", "범용 하드웨어 통합", "Python 기반의 가벼운 도메인 워크플로"],
    ["QCoDeS", "드라이버·Dataset·메타데이터", "범용 연구 데이터 프레임워크", "현장 GUI와 영상·열 제어의 결합"],
    ["PyMeasure", "Procedure·Worker·GUI·Sequencer", "일반 계측 절차 실행", "AI가 만드는 검증형 실험 플러그인"],
    ["Bluesky", "스트리밍·중단 복구·재현성", "대규모 시설형 실행 엔진", "소규모 연구실용 안전·승인 UX"],
    ["UOSLabManager", "온도·전원·카메라·RHEED 통합", "장비 수 경쟁", "멀티모달 폐루프 + 안전한 AI 확장"],
  ];
  const table = slide.tables.add({
    rows: values.length,
    columns: 4,
    left: 41.33,
    top: 214,
    width: 1197.33,
    height: 412,
    columnWidths: [175, 310, 320, 392.33],
    values,
  });
  table.styleOptions = { headerRow: true, bandedRows: true, firstColumn: true };
  table.borders.assign({ style: "solid", fill: COLORS.rule, width: 1 });
  for (let c = 0; c < 4; c += 1) {
    table.getCell(0, c).fill = COLORS.ink;
    table.getCell(0, c).text.style = { fontSize: 17, typeface: FONT, bold: true, color: COLORS.white };
  }
  for (let r = 1; r < values.length; r += 1) {
    for (let c = 0; c < 4; c += 1) {
      table.getCell(r, c).text.style = { fontSize: 15.5, typeface: FONT, color: COLORS.ink };
    }
  }
  for (let c = 0; c < 4; c += 1) {
    table.getCell(values.length - 1, c).fill = COLORS.pale;
    table.getCell(values.length - 1, c).text.style = { fontSize: 15.5, typeface: FONT, bold: true, color: COLORS.ink };
  }
  addText(slide, "competitor-footer", "10", { left: 1184.18, top: 659.24, width: 54.48, height: 25.33 }, 13.33, { alignment: "right" });
  addSectionMark(slide, "POSITIONING");
  return slide;
}

async function main() {
  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  // 1. Cover
  let slide = buildSlide01(presentation, {
    title: para("UOSLabManager", 24, { bold: true }),
    title2: para("프로그램 분석과\n개선 로드맵", 74, { bold: true, lineSpacingPercent: 93000 }),
    title3: para("실험실 장비 통합에서\n안전한 AI 실험 운영 플랫폼으로", 26, { color: COLORS.muted, lineSpacingPercent: 108000 }),
  });
  slide.shapes.add({ geometry: "rect", name: "cover-accent", position: { left: 1120, top: 0, width: 160, height: 720 }, fill: COLORS.pale, line: { style: "solid", fill: "none", width: 0 } });
  slide.shapes.add({ geometry: "rect", name: "cover-accent-strong", position: { left: 1248, top: 0, width: 32, height: 720 }, fill: COLORS.accentStrong, line: { style: "solid", fill: "none", width: 0 } });
  notes(slide, ["README.md", "Repository analysis dated 2026-08-10"], "발표 목적: 현재 프로그램을 이해하고, 안정화와 차별화를 동시에 달성하는 개발 방향을 제안합니다.");

  // 2. Program at a glance
  slide = buildSlide19(presentation, {
    title: para("하나의 데스크톱이 측정·제어·영상·레시피를 연결한다", 38.67, { bold: true }),
    body1: {
      topic: para("현재 범위", 20, { bold: true }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: para("PyQt6 기반 데스크톱 앱으로 장비 운용, 실시간 모니터링, 데이터 기록, 카메라 처리, 실험 시퀀스와 플러그인 제작을 통합합니다.", 19, { color: COLORS.muted }),
    },
    stat1: para("5", 58, { bold: true, color: COLORS.accentStrong }),
    stat2: para("2", 58, { bold: true, color: COLORS.accentStrong }),
    stat3: para("97", 58, { bold: true, color: COLORS.accentStrong }),
    body2: para("장비 플러그인\n온도·전원·SMU·열화상", 18, { bold: true }),
    body3: para("사용자 실험\nHeating Control·Thermo1", 18, { bold: true }),
    body4: para("선언된 테스트\n안전·프로토콜 중심", 18, { bold: true }),
    footer1: "2",
  });
  addSectionMark(slide, "OVERVIEW");
  notes(slide, ["plugins/devices/*/plugin.py", "user_plugins/experiments/*/plugin.py", "tests/*.py"], "숫자는 현재 작업 트리에서 확인한 저장소 기준입니다.");

  // 3. Architecture
  slide = buildSlide05(presentation, {
    title: para("플러그인 확장은 좋지만 실행 책임이 GUI에 남아 있다", 38.67, { bold: true }),
    body1: pair("구조의 중심", "MainWindow가 대시보드, 측정, 시퀀스, 카메라, Plugin Studio를 조립합니다. DeviceManager는 장비별 워커를 생성하고 최신 측정값과 상태를 공유합니다.", 19),
    body2: pair("", "", 18),
    footer1: "3",
  });
  // connectors first
  addVerticalConnector(slide, "arch-edge-1", 946, 262, 42);
  addVerticalConnector(slide, "arch-edge-2", 946, 364, 42);
  addVerticalConnector(slide, "arch-edge-3", 946, 466, 42);
  addNode(slide, "arch-ui", "UI · Workflow", "Dashboard · Data · Sequence · Camera · Plugin Studio", { left: 690, top: 205, width: 512, height: 78 }, { fill: COLORS.pale, line: COLORS.accentStrong });
  addNode(slide, "arch-core", "Core Services", "DeviceManager · SequenceEngine · DataLogger", { left: 690, top: 307, width: 512, height: 78 });
  addNode(slide, "arch-plugin", "Plugin API", "DevicePlugin · ExperimentPlugin · SequenceCommand", { left: 690, top: 409, width: 512, height: 78 });
  addNode(slide, "arch-hw", "Hardware & Streams", "Serial · VISA · CTvideo · USB camera · RHEED profile", { left: 690, top: 511, width: 512, height: 78 }, { fill: "#FAFAFA" });
  addSectionMark(slide, "ARCHITECTURE");
  notes(slide, ["gui/main_window.py", "core/device_manager.py", "core/plugin_manager.py", "core/sequence_engine.py", "core/data_logger.py"], "핵심 판단: 플러그인 경계는 좋지만 시퀀스 실행과 장비별 분기가 GUI 패널에 집중되어 있습니다.");

  // 4. Operation flow
  slide = buildSlide17(presentation, {
    title: para("실험은 연결 → 관찰 → 실행의 세 단계로 흐른다", 38.67, { bold: true }),
    label1: para("01  CONNECT", 18, { bold: true, color: COLORS.accentStrong }),
    label2: para("02  OBSERVE", 18, { bold: true, color: COLORS.accentStrong }),
    label3: para("03  EXECUTE", 18, { bold: true, color: COLORS.accentStrong }),
    body1: pair("장비 연결", "플러그인이 포트·주소를 받아 드라이버를 만들고 전용 워커가 주기 측정을 시작합니다.", 17.5),
    body2: pair("실시간 관찰", "최신 값은 그래프·표·로그로 표시되며 카메라와 RHEED profile도 함께 수집됩니다.", 17.5),
    body3: pair("레시피 실행", "장비 명령과 실험 플러그인 명령을 순서대로 실행하고 상태를 polling합니다.", 17.5),
    footer1: "4",
  });
  addSectionMark(slide, "WORKFLOW");
  notes(slide, ["core/device_manager.py", "gui/panel_measurement.py", "gui/panel_sequence.py", "gui/panel_camera.py"], "이 흐름이 제품 사용자의 기본 경험입니다.");

  // 5. Coverage
  slide = buildSlide16(presentation, {
    title: para("현재 자산은 열·전기·영상 실험에 집중되어 있다", 38.67, { bold: true }),
    body1: pair("LakeShore 331", "온도·센서·setpoint·PID·heater·ramp", 15.5),
    body2: pair("Keithley 2400", "전압 소스·전류·전력·저항·compliance", 15.5),
    body3: pair("ZUP36-12", "전압·전류·OVP/UVP·fault·출력 제어", 15.5),
    body4: pair("GPD-3303S", "2채널 설정·tracking·상태·출력 안전", 15.5),
    body5: pair("CTvideo 3M", "온도·교정·vendor control·응답 상태", 15.5),
    body6: pair("Camera / RHEED", "녹화·표시 처리·1D profile 동기화", 15.5),
    body7: pair("Heating Control", "preheat·PID·ramp·센서 유효성·safe output", 15.5),
    body8: pair("Plugin Studio", "생성·편집·검증·reload·Codex diff 승인", 15.5),
    footer1: "5",
  });
  addSectionMark(slide, "CAPABILITIES");
  notes(slide, ["plugins/devices/*", "gui/panel_camera.py", "gui/panel_ctvideo.py", "user_plugins/experiments/heating_control/panel.py", "gui/plugin_studio/*"], "지원 범위를 제품 포지셔닝의 출발점으로 사용합니다.");

  // 6. Safety
  slide = buildSlide13(presentation, {
    title: para("안전 설계 의식은 분명하지만 독립 안전 계층은 아직 없다", 38.67, { bold: true }),
    body1: point("장비 워커", "장비별 명령을 직렬화하고 polling 실패가 누적되면 연결을 종료합니다."),
    body2: point("데이터 freshness", "Heating Control은 온도·전원 데이터가 2초 이상 stale이면 제어를 중단합니다."),
    body3: point("Safe output", "종료 시 output off, 전압·전류 0 설정을 순차 시도하고 실패도 보고합니다."),
    body4: point("Software STOP", "메인 창이 heater/output off를 요청한 뒤 전체 연결을 닫습니다. 단, UI가 멈추면 반응성도 함께 저하됩니다."),
    footer1: "6",
  });
  addSectionMark(slide, "SAFETY");
  notes(slide, ["core/device_manager.py:34-83", "user_plugins/experiments/heating_control/panel.py:29-75", "user_plugins/experiments/heating_control/panel.py:298-311", "gui/main_window.py:444-466"], "현재 장점과 한계를 함께 설명합니다. 소프트웨어 STOP은 물리 비상정지의 대체가 아닙니다.");

  // 7. Plugin Studio
  slide = buildSlide11(presentation, {
    title: para("Plugin Studio는 가장 강한 차별화 후보다", 38.67, { bold: true }),
    body1: {
      topic: para("앱 안에서 실험 플러그인을 만들고 수정하며, Codex 변경은 임시 staging 공간에만 적용됩니다.", 20, { bold: true }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: para("사용자는 unified diff와 변경된 줄을 확인한 후 Apply 또는 Reject를 선택합니다.", 18.5, { color: COLORS.muted }),
      loremIpsumDolorSitAmetConsecteturAdipiscing2: para("문법·manifest 검증과 reload까지 한 흐름으로 묶여 있습니다.", 18.5, { color: COLORS.muted }),
    },
    body2: para("AI가 제안", 27, { bold: true, color: COLORS.accentStrong }),
    body3: para("사람이 승인", 27, { bold: true, color: COLORS.accentStrong }),
    body4: {
      detailGoesHere: para("격리 staging", 17.5, { bold: true }),
      detailGoesHere2: para("파일 diff", 17.5),
      detailGoesHere3: para("token 사용량 표시", 17.5),
    },
    body5: {
      detailGoesHere: para("Apply / Reject", 17.5, { bold: true }),
      detailGoesHere2: para("변경 충돌 감지", 17.5),
      detailGoesHere3: para("검증 후 reload", 17.5),
    },
    footer1: "7",
  });
  addSectionMark(slide, "PLUGIN STUDIO");
  notes(slide, ["gui/plugin_studio/codex_panel.py", "gui/plugin_studio/studio_panel.py", "core/plugin_manager.py"], "단순 코드 생성보다 검증·승인·rollback까지 제품화하는 것이 중요합니다.");

  // 8. Strengths
  slide = buildSlide06(presentation, {
    title: para("제품의 강점은 범용성보다 ‘현장 통합’에 있다", 38.67, { bold: true }),
    body1: pair("실험 맥락 통합", "온도·전원·카메라·RHEED를 한 작업공간에서 보고 제어합니다.", 18),
    body2: pair("안전 우선 구현", "출력 확인, EEPROM 쓰기 승인, stale-data 감지와 safe shutdown 테스트가 존재합니다.", 18),
    body3: pair("사용자 확장", "장비와 실험을 플러그인으로 분리했고 앱 안에서 수정·재로딩할 수 있습니다.", 18),
    footer1: "8",
  });
  addSectionMark(slide, "STRENGTHS");
  notes(slide, ["core/plugin_manager.py", "tests/test_ctvideo_camera_controls.py", "tests/test_gpd3303s.py", "user_plugins/experiments/heating_control/panel.py"], "기능 목록이 아니라 왜 연구 현장에 가치가 있는지를 강조합니다.");

  // 9. Limitations
  slide = buildSlide09(presentation, {
    title: para("제품화의 병목은 실행 안정성·데이터 재현성·플러그인 신뢰다", 38.67, { bold: true }),
    body1: {
      topic: para("현재 코드는 기능 검증형 프로토타입으로는 강하지만, 무인·장시간 실험을 맡기기 위한 구조는 보완이 필요합니다.", 20, { bold: true }),
      loremIpsumDolorSitAmetConsecteturAdipiscing: para("핵심 위험은 세 영역에 집중됩니다.", 18.5, { color: COLORS.muted }),
      loremIpsumDolorSitAmetConsecteturAdipiscing2: para("", 18),
    },
    body2: pair("실행 엔진", "GUI timer 안에서 동기 장비 호출과 sleep을 수행하며 명령 schema도 장비명에 하드코딩되어 있습니다.", 17),
    body3: pair("Run 데이터", "측정값을 메모리에 모아 수동 CSV/NPY로 저장하므로 crash recovery와 실험 provenance가 약합니다.", 17),
    body4: pair("플러그인 신뢰", "문법 검증은 있지만 적용된 Python 플러그인은 본 프로세스에서 전체 권한으로 실행됩니다.", 17),
    footer1: "9",
  });
  addSectionMark(slide, "GAPS");
  notes(slide, ["gui/panel_sequence.py:440-558", "core/data_logger.py", "gui/plugin_studio/studio_panel.py:211-278", "core/plugin_manager.py:106-149"], "세 문제는 각각 비동기 실행 엔진, Run 저장소, capability 기반 플러그인 정책으로 해결할 수 있습니다.");

  // 10. Competitive landscape
  slide = buildCompetitorSlide(presentation);
  notes(slide, [
    "https://www.ni.com/en/support/downloads/software-products/download.labview.html.html",
    "https://microsoft.github.io/Qcodes/",
    "https://pymeasure.readthedocs.io/en/stable/api/experiment/procedure.html",
    "https://blueskyproject.io/bluesky/main/index.html",
  ], "비교의 목적은 우열 평가가 아니라 UOSLabManager가 차별화할 영역을 좁히는 것입니다.");

  // 11. Positioning
  slide = buildSlide06(presentation, {
    title: para("추천 포지션은 ‘안전한 AI 멀티모달 실험 운영 플랫폼’이다", 38.67, { bold: true }),
    body1: pair("도메인 특화", "열처리·박막·광학 실험을 중심으로 CTvideo, 전원, 온도, RHEED 데이터를 동기화합니다.", 18),
    body2: pair("검증형 AI 확장", "자연어로 플러그인을 만들되 시뮬레이션, 정책 검사, 테스트, 사람 승인과 rollback을 필수화합니다.", 18),
    body3: pair("재현성과 안전", "모든 Run에 장비 상태, 레시피, 교정값, 플러그인 버전, 경고와 사용자 조작을 남깁니다.", 18),
    footer1: "11",
  });
  slide.shapes.add({ geometry: "rect", name: "positioning-accent", position: { left: 41, top: 184, width: 1198, height: 8 }, fill: COLORS.accentStrong, line: { style: "solid", fill: "none", width: 0 } });
  addSectionMark(slide, "DIFFERENTIATION");
  notes(slide, ["Repository analysis and competitor sources from slide 10"], "핵심 문장: 장비를 많이 지원하는 앱이 아니라, AI 확장과 안전·재현성을 함께 보장하는 실험 운영 플랫폼입니다.");

  // 12. Future architecture
  slide = buildSlide13(presentation, {
    title: para("미래 구조는 모든 명령을 검증·기록·중단 가능하게 만든다", 38.67, { bold: true }),
    body1: point("Declarative Command API", "장비가 명령·타입·범위·단위·완료 조건·safe-state를 선언합니다."),
    body2: point("Safety Supervisor", "UI와 분리된 watchdog이 absolute limit, freshness와 interlock을 감시합니다."),
    body3: point("Run & Provenance Store", "측정값을 즉시 저장하고 레시피·장비·교정·코드 버전을 함께 보존합니다."),
    body4: point("AI Plugin Lifecycle", "mock test → dry-run → 정책 검사 → 승인 → 적용 → rollback을 표준 절차로 묶습니다."),
    footer1: "12",
  });
  slide.shapes.add({ geometry: "roundRect", name: "future-principle", position: { left: 325, top: 610, width: 630, height: 42 }, fill: COLORS.pale, line: { style: "solid", fill: COLORS.accentStrong, width: 1 }, borderRadius: "rounded-xl" });
  addText(slide, "future-principle-text", "공통 원칙 · 모든 명령은 검증되고, 기록되며, 즉시 중단 가능해야 한다", { left: 345, top: 621, width: 590, height: 22 }, 15.5, { bold: true, alignment: "center" });
  addSectionMark(slide, "TARGET");
  notes(slide, ["Recommended target architecture derived from repository analysis"], "네 구성 요소는 독립 기능이 아니라 하나의 실행 경로로 결합되어야 합니다.");

  // 13. Roadmap
  slide = buildSlide18(presentation, {
    title: para("3단계 로드맵은 안정화 후 차별화를 확장한다", 38.67, { bold: true }),
    body1: pair("기반 안정화", "비동기 시퀀스 엔진\n중앙 Safety Supervisor\n자동 Run 저장·crash recovery\n의존성 lock·CI·mock 장비", 17),
    body2: pair("Plugin Studio 제품화", "capability manifest\n자동 test·dry-run·rollback\n선언형 명령 schema\n플러그인 SDK와 예제", 17),
    body3: pair("도메인 차별화", "영상·센서 시간 동기화\nRHEED 특징·endpoint 검출\n멀티모달 폐루프 제어\n원격 모니터링·리포트", 17),
    label1: para("0–2개월", 22, { bold: true, color: COLORS.accentStrong }),
    label2: para("2–5개월", 22, { bold: true, color: COLORS.accentStrong }),
    label3: para("5–9개월", 22, { bold: true, color: COLORS.accentStrong }),
    footer1: "13",
  });
  addSectionMark(slide, "ROADMAP");
  notes(slide, ["Roadmap recommendation based on repository architecture and product positioning"], "기간은 1~2명의 핵심 개발자가 기존 기능을 유지하며 진행한다는 가정의 상대적 순서입니다. 실제 일정은 팀 규모와 장비 접근성에 따라 재산정해야 합니다.");

  // 14. Close
  slide = buildSlide26(presentation, {
    title: para("NEXT", 24, { bold: true, color: COLORS.accentStrong }),
    title2: para("먼저 실행을\n신뢰할 수 있게", 70, { bold: true, lineSpacingPercent: 93000 }),
    title3: {
      loremIpsumDetails: para("1  비동기 시퀀스 엔진", 24, { bold: true }),
      loremIpsumDetails2: para("2  자동 Run 기록", 24, { bold: true }),
      loremIpsumDetails3: para("3  안전 검증형 Plugin Studio", 24, { bold: true }),
    },
  });
  slide.shapes.add({ geometry: "rect", name: "close-accent", position: { left: 1120, top: 0, width: 160, height: 720 }, fill: COLORS.pale, line: { style: "solid", fill: "none", width: 0 } });
  slide.shapes.add({ geometry: "rect", name: "close-accent-strong", position: { left: 1248, top: 0, width: 32, height: 720 }, fill: COLORS.accentStrong, line: { style: "solid", fill: "none", width: 0 } });
  notes(slide, ["Slides 9, 11, 12, and 13 synthesis"], "우선순위는 안전한 실행 기반을 먼저 만들고, 그 위에 AI와 도메인 차별화를 쌓는 것입니다.");

  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  for (const [index, currentSlide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await presentation.export({ slide: currentSlide, format: "png", scale: 1 });
    await fs.writeFile(`${OUTPUT_DIR}/${stem}.png`, Buffer.from(await png.arrayBuffer()));
    const layout = await currentSlide.export({ format: "layout" });
    await fs.writeFile(`${OUTPUT_DIR}/${stem}.layout.json`, await layout.text(), "utf8");
  }
  const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
  await fs.writeFile(`${OUTPUT_DIR}/deck-montage.webp`, Buffer.from(await montage.arrayBuffer()));

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(FINAL_PPTX);
  console.log(`Saved ${presentation.slides.items.length} slides to ${FINAL_PPTX}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
