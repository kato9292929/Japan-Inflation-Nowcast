// 実物スキーマ回帰テスト: JIN が出す v1/v2 leg を、AA が使うのと同じ
// @x402/core@2.17.0 の PaymentRequirements スキーマに直接通す。
// これで「top-level 必須フィールドの欠落」が PayAI /verify ではなく CI で落ちる。
// 実行: npx tsx --test tests/js/schema-compliance.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildLegs } from "../../src/lib/x402";
import { PaymentRequirementsV1Schema, PaymentRequirementsV2Schema } from "@x402/core/schemas";

const RESOURCE = "https://jin-orcin-pi.vercel.app/api/jin/movers";
const FEE_PAYER = "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4";
const OPTS = { price: "$0.02", description: "JIN daily inflation nowcast movers", resourcePath: "/api/jin/movers" };

test("(i) v1 + v2 leg が実物 @x402/core PaymentRequirements スキーマを通る", () => {
  const legs = buildLegs(OPTS, FEE_PAYER, RESOURCE);
  const v1 = legs.find((l) => !l.network.includes(":"));
  const v2 = legs.find((l) => l.network.includes(":"));
  assert.ok(v1 && v2, "v1/v2 両 leg が存在する（length 2）");
  const r1 = PaymentRequirementsV1Schema.safeParse(v1);
  assert.ok(r1.success, "v1: " + JSON.stringify(r1.success ? [] : r1.error.issues));
  const r2 = PaymentRequirementsV2Schema.safeParse(v2);
  assert.ok(r2.success, "v2: " + JSON.stringify(r2.success ? [] : r2.error.issues));
});

test("(i2) 両 leg に top-level resource/description/mimeType/maxTimeoutSeconds がある", () => {
  const legs = buildLegs(OPTS, FEE_PAYER, RESOURCE);
  for (const leg of legs) {
    for (const f of ["resource", "description", "mimeType", "maxTimeoutSeconds"] as const) {
      assert.ok(
        (leg as unknown as Record<string, unknown>)[f] !== undefined,
        `${leg.network} missing ${f}`,
      );
    }
  }
});

test("(i3) v1=maxAmountRequired / v2=amount、値は同一、maxTimeoutSeconds=300", () => {
  const [v1, v2] = buildLegs(OPTS, FEE_PAYER, RESOURCE);
  assert.equal((v1 as Record<string, unknown>).maxAmountRequired, "20000");
  assert.equal((v2 as Record<string, unknown>).amount, "20000");
  assert.equal(v1.maxTimeoutSeconds, 300);
  assert.equal(v2.maxTimeoutSeconds, 300);
});
