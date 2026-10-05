import SwiftUI

/// Settings › Billing (0068) — the workspace's plan, this month's usage,
/// and the plans it can move to. Mirrors the web's `/settings/billing`.
///
/// Admins only: the server answers 403 to everyone else, and the sidebar
/// row is hidden for them. Payments are not connected yet — a switch
/// applies at once where the server allows it and is refused with a
/// reason where it does not. When Stripe arrives the server answers
/// `redirect` and this view opens the URL in the browser.
struct BillingView: View {
    @EnvironmentObject private var app: AppState
    @State private var billing: Billing?
    @State private var loading = true
    @State private var error: String?
    @State private var pending: BillingPlan?
    @State private var busy = false
    /// The interval the plans are priced in; nil = what the workspace pays.
    @State private var chosenYearly: Bool?
    @State private var redeeming = false
    @State private var code = ""
    @State private var codeError: String?
    @State private var codeBusy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if loading {
                ProgressView().controlSize(.small)
            } else if let error, billing == nil {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            } else if let billing {
                content(billing)
            }
        }
        .task { await load() }
        .confirmationDialog(
            pending.map { $0.code == billing?.plan.code ? "Pay for \($0.name) \(intervalWord)?" : "Switch to \($0.name)?" } ?? "",
            isPresented: Binding(get: { pending != nil }, set: { if !$0 { pending = nil } }),
            titleVisibility: .visible
        ) {
            if let plan = pending {
                Button(plan.code == billing?.plan.code ? "Switch to \(intervalWord)" : "Switch to \(plan.name)") {
                    Task { await switchTo(plan) }
                }
                Button("Cancel", role: .cancel) { pending = nil }
            }
        } message: {
            if let plan = pending {
                Text("\(plan.priceText(yearly: showYearly)). The change applies to this workspace at once.")
            }
        }
    }

    @ViewBuilder
    private func content(_ b: Billing) -> some View {
        // ── The plan ────────────────────────────────────────────────
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(b.plan.name).font(.ds(15, .semibold)).foregroundStyle(DS.text1)
                Spacer()
                Text(b.plan.priceText(yearly: b.subscription?.isYearly == true))
                    .font(.ds(13)).foregroundStyle(DS.text1)
            }
            Text(b.plan.summary).font(.dsMeta).foregroundStyle(DS.muted)
            if let sub = b.subscription {
                if sub.status == "past_due" {
                    DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill",
                             text: "The last payment did not go through. Update the payment method to keep \(b.plan.name).")
                }
                if let end = sub.currentPeriodEnd {
                    Text("\(sub.provider == "code" ? "From a code · ends" : sub.cancelAtPeriodEnd ? "Ends" : "Renews") on \(end.formatted(date: .abbreviated, time: .omitted)).")
                        .font(.dsMeta).foregroundStyle(DS.muted)
                }
            }
            if b.canEdit { redeemRow }
            if !b.paymentsConnected {
                Text("Payments aren't connected yet — invoices and the payment method will appear here.")
                    .font(.dsMeta).foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .dsCard()

        // ── Usage this month ────────────────────────────────────────
        VStack(alignment: .leading, spacing: 12) {
            Text("Usage in \(b.periodStart.formatted(.dateTime.month(.wide)))")
                .font(.ds(13, .semibold)).foregroundStyle(DS.text1)
            ForEach(b.usage) { meter in
                VStack(alignment: .leading, spacing: 5) {
                    HStack {
                        Text(meter.label).font(.ds(12.5)).foregroundStyle(DS.text1)
                        Spacer()
                        Text(meter.text).font(.ds(12.5)).monospacedDigit().foregroundStyle(DS.muted)
                    }
                    if let share = meter.share {
                        UsageBar(share: share)
                    }
                }
            }
        }
        .dsCard()

        // ── Plans ───────────────────────────────────────────────────
        HStack {
            Text("Plans").font(.ds(13, .semibold)).foregroundStyle(DS.text1)
            Spacer()
            Picker("Billing interval", selection: Binding(get: { showYearly }, set: { chosenYearly = $0 })) {
                Text("Monthly").tag(false)
                Text(yearlySaving(b.plans) > 0 ? "Yearly · save \(yearlySaving(b.plans))%" : "Yearly").tag(true)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
        }
        HStack(alignment: .top, spacing: 12) {
            ForEach(b.plans) { plan in
                planCard(plan, billing: b)
            }
        }
        if let error {
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
        }
    }

    private func planCard(_ plan: BillingPlan, billing b: Billing) -> some View {
        let samePlan = plan.code == b.plan.code
        // On this plan AND paying this way; a plan with no yearly price has one way.
        let isCurrent = samePlan
            && (plan.yearlyPriceCents == nil || showYearly == (b.subscription?.isYearly == true))
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(plan.name).font(.ds(13.5, .semibold)).foregroundStyle(DS.text1)
                Spacer()
                if isCurrent {
                    Text("Current").font(.ds(10.5, .medium)).foregroundStyle(DS.muted)
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .background(Capsule().fill(DS.surface2))
                }
            }
            Text(plan.priceText(yearly: showYearly)).font(.ds(12.5)).foregroundStyle(DS.text1)
                .fixedSize(horizontal: false, vertical: true)
            Text(plan.summary).font(.dsMeta).foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(plan.features, id: \.self) { feature in
                Text("• \(feature)").font(.dsMeta).foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            if b.canEdit && !isCurrent {
                if plan.selfServe {
                    Button(samePlan ? "Switch to \(intervalWord)" : "Switch to \(plan.name)") { pending = plan }
                        .buttonStyle(DSButtonStyle(
                            kind: (plan.priceCents ?? 0) > (b.plan.priceCents ?? 0) ? .primary : .secondary,
                            size: 12.5, height: 28))
                        .disabled(busy || !b.paymentsConnected)
                        .help(b.paymentsConnected ? "" : "Payments aren't connected yet")
                } else {
                    Text("Get in touch to set it up.").font(.dsMeta).foregroundStyle(DS.muted)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .dsCard()
        .overlay(
            RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                .stroke(isCurrent ? DS.accent : .clear, lineWidth: 1)
        )
    }

    /// "Have a code?" — a link that opens one field (0069).
    @ViewBuilder
    private var redeemRow: some View {
        if !redeeming {
            Button("Have a code?") { redeeming = true }
                .buttonStyle(.link)
                .font(.ds(12.5))
                .padding(.top, 4)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                Divider().overlay(DS.line)
                Text("REDEEM CODE").font(.ds(10.5, .semibold)).tracking(0.8).foregroundStyle(DS.muted)
                HStack(spacing: 8) {
                    TextField("XXXX-XXXX-XXXX-XXXX", text: $code)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 13, design: .monospaced))
                        .frame(maxWidth: 260)
                        .onSubmit { Task { await redeem() } }
                        .onChange(of: code) { _, value in
                            if value != value.uppercased() { code = value.uppercased() }
                            codeError = nil
                        }
                    Button("Redeem") { Task { await redeem() } }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 12.5, height: 28))
                        .disabled(codeBusy || code.trimmingCharacters(in: .whitespaces).isEmpty)
                    Button("Cancel") { redeeming = false; code = ""; codeError = nil }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12.5, height: 28))
                        .disabled(codeBusy)
                }
                if let codeError {
                    Text(codeError).font(.dsMeta).foregroundStyle(DS.danger)
                }
            }
            .padding(.top, 4)
        }
    }

    private var showYearly: Bool { chosenYearly ?? (billing?.subscription?.isYearly == true) }
    private var intervalWord: String { showYearly ? "yearly" : "monthly" }

    /// The best yearly saving in the catalogue, in whole percent.
    private func yearlySaving(_ plans: [BillingPlan]) -> Int {
        let best = plans.compactMap { p -> Double? in
            guard let month = p.priceCents, month > 0, let year = p.yearlyPriceCents else { return nil }
            return 1 - Double(year) / Double(12 * month)
        }.max() ?? 0
        return Int((best * 100).rounded())
    }

    // MARK: - Actions

    private func redeem() async {
        let value = code.trimmingCharacters(in: .whitespaces)
        guard !value.isEmpty, !codeBusy else { return }
        codeBusy = true
        defer { codeBusy = false }
        do {
            billing = try await app.api.redeemCode(value).billing
            code = ""
            redeeming = false
            error = nil
        } catch {
            codeError = Self.message(error)
        }
    }

    private func load() async {
        loading = billing == nil
        do {
            billing = try await app.api.billing()
            error = nil
        } catch {
            self.error = Self.message(error)
        }
        loading = false
    }

    private func switchTo(_ plan: BillingPlan) async {
        busy = true
        pending = nil
        defer { busy = false }
        do {
            let result = try await app.api.changePlan(plan.code, yearly: showYearly)
            if result.action == "redirect", let raw = result.redirectURL, let url = URL(string: raw) {
                NSWorkspace.shared.open(url)
                return
            }
            billing = result.billing
            error = nil
        } catch {
            self.error = Self.message(error)
            await load()
        }
    }

    private static func message(_ error: Error) -> String {
        switch (error as? APIError)?.code {
        case "billing_not_connected": return "Payments aren't connected yet, so the plan can't change here."
        case "plan_contact_sales": return "Enterprise is arranged with us — get in touch and we'll set it up."
        case "redeem_unknown": return "That code isn't valid. Check it and try again."
        case "redeem_expired": return "That code has expired."
        case "redeem_used_up": return "That code has already been used as many times as it allows."
        case "redeem_already": return "This workspace has already used that code."
        case "redeem_rate_limited": return "Too many tries. Wait a while and try again."
        default: return (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }
}

/// A thin meter: moss below 80 %, amber to the limit, red at it.
private struct UsageBar: View {
    let share: Double

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(DS.surface2)
                Capsule().fill(share >= 1 ? DS.danger : share >= 0.8 ? DS.warn : DS.accent)
                    .frame(width: geo.size.width * share)
            }
        }
        .frame(height: 6)
        .accessibilityElement()
        .accessibilityLabel("\(Int((share * 100).rounded())) percent used")
    }
}
