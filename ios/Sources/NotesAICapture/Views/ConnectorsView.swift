import SwiftUI
import UIKit

/// Settings › Connectors: Google Calendar and calendar links on the
/// server, this phone's own calendars (which accounts feed the home
/// page's Coming up list), and the remote MCP servers the user has
/// connected — HubSpot, Notion, a custom one.
struct ConnectorsView: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var calendar: CalendarService
    @ObservedObject var google: GoogleCalendarService
    @ObservedObject var store: ConnectorStore
    @State private var editing: Connector?
    @State private var pendingRemoval: Connector?
    @State private var pendingDisconnect: CalendarConnection?
    @State private var addingLink = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                googleCard
                calendarCard
                connectorsCard
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 12)
        }
        .background(DS.bg)
        .navigationTitle("Connectors")
        .navigationBarTitleDisplayMode(.inline)
        .alert(Text(pendingDisconnect?.isLink == true ? "Remove this calendar link?" : "Disconnect this Google account?"),
               isPresented: Binding(
            get: { pendingDisconnect != nil }, set: { if !$0 { pendingDisconnect = nil } }
        )) {
            Button(pendingDisconnect?.isLink == true ? "Remove" : "Disconnect", role: .destructive) {
                if let connection = pendingDisconnect { Task { await google.disconnect(connection.id) } }
                pendingDisconnect = nil
            }
            Button("Cancel", role: .cancel) { pendingDisconnect = nil }
        } message: {
            Text(pendingDisconnect?.isLink == true
                 ? "Its events leave the Coming up list here and in the web app. The calendar itself is untouched."
                 : "Its events leave the Coming up list here and in the web app. Nothing changes in Google Calendar.")
        }
        .sheet(isPresented: $addingLink) {
            CalendarLinkSheet(google: google) { addingLink = false }
        }
        .sheet(item: $editing) { connector in
            ConnectorEditor(connector: connector, store: store) { editing = nil }
        }
        .alert("Remove this connector?", isPresented: Binding(
            get: { pendingRemoval != nil }, set: { if !$0 { pendingRemoval = nil } }
        )) {
            Button("Remove", role: .destructive) {
                if let connector = pendingRemoval { store.remove(connector.id) }
                pendingRemoval = nil
            }
            Button("Cancel", role: .cancel) { pendingRemoval = nil }
        } message: {
            Text("Its sign-in is forgotten on this phone. Nothing changes on the other side.")
        }
        .onAppear { calendar.recheckAccess() }
        .task { await google.refresh() }
    }

    // MARK: - Google Calendar & calendar links (server-side connections)

    private var googleCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                ConnectorGlyph(symbol: "calendar.badge.clock")
                VStack(alignment: .leading, spacing: 2) {
                    Text(google.linkAvailable ? "Google Calendar & calendar links" : "Google Calendar")
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    Text(googleSubtitle)
                        .font(.dsMeta)
                        .foregroundStyle(google.error == nil ? DS.muted : DS.dangerText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 4)
                googleChip
            }
            HStack(spacing: 8) {
                if google.available != false {
                    Button(google.isConnected ? "Add account" : "Connect") { Task { await google.connect() } }
                        .buttonStyle(DSButtonStyle(kind: google.isConnected ? .secondary : .primary,
                                                   size: 14, height: 36, fill: true))
                        .disabled(google.connecting)
                }
                if google.linkAvailable {
                    // The no-client-id way in: primary when it is the only one.
                    Button("Add link") { addingLink = true }
                        .buttonStyle(DSButtonStyle(kind: google.available == false && !google.isConnected ? .primary : .secondary,
                                                   size: 14, height: 36, fill: true))
                }
            }
            ForEach(google.connections) { connection in
                DSDivider()
                googleAccount(connection)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private var googleSubtitle: String {
        if let error = google.error { return error }
        switch google.available {
        case nil: return "Checking the server…"
        case .some(false) where !google.isConnected:
            return google.linkAvailable
                ? "Google sign-in is not set up on this server — add a calendar by its private iCal address instead."
                : "Not set up on this server (GOOGLE_CALENDAR_CLIENT_ID)."
        default:
            if google.isConnected { return "Next 7 days on the home page, here and in the web app." }
            return google.linkAvailable
                ? "Connect an account or add a calendar link: the next meetings show on the home page, here and in the web app."
                : "Connect an account: its next meetings show on the home page, here and in the web app."
        }
    }

    @ViewBuilder
    private var googleChip: some View {
        if google.connecting {
            DSChip(text: "Connecting", tint: DS.info, soft: DS.infoSoft, dot: true)
        } else if google.connections.contains(where: \.needsReauth) {
            DSChip(text: "Sign in", tint: DS.warn, soft: DS.warnSoft)
        } else if google.isConnected {
            DSChip(text: google.connections.count == 1 ? "Connected" : "\(google.connections.count) connected",
                   tint: DS.ok, soft: DS.okSoft)
        } else if google.available == false, !google.linkAvailable {
            DSChip(text: "Not set up", tint: DS.muted, soft: DS.surface2)
        } else {
            DSChip(text: "Not connected", tint: DS.muted, soft: DS.surface2)
        }
    }

    /// One connected account or link: its address, a Sign-in-again nudge
    /// when Google dropped the token, and the calendars to include.
    private func googleAccount(_ connection: CalendarConnection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                if connection.isLink {
                    Image(systemName: "link")
                        .font(.ds(12, .medium))
                        .foregroundStyle(DS.muted)
                }
                Text(connection.accountEmail)
                    .font(.ds(14, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                if let error = connection.lastError, connection.isLink {
                    Text(error == "feed_gone" ? "Link no longer works" : "Couldn't fetch")
                        .font(.ds(11, .medium))
                        .foregroundStyle(DS.warn)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(DS.warnSoft))
                }
                Spacer(minLength: 6)
                DSMenu(dim: true) {
                    var items: [DSMenuItem] = []
                    if connection.needsReauth {
                        items.append(.item("Sign in again", symbol: "person.badge.key") {
                            Task { await google.connect(loginHint: connection.accountEmail) }
                        })
                    }
                    if !connection.needsReauth, google.calendars[connection.id] == nil {
                        items.append(.item("Choose calendars…", symbol: "calendar") {
                            Task { await google.loadCalendars(for: connection.id) }
                        })
                    }
                    if !items.isEmpty { items.append(.separator) }
                    items.append(.item(connection.isLink ? "Remove" : "Disconnect", symbol: "xmark.circle", danger: true) {
                        pendingDisconnect = connection
                    })
                    return items
                }
            }
            if let list = google.calendars[connection.id] {
                ForEach(list) { item in
                    HStack(spacing: 8) {
                        Circle()
                            .fill(Color(hexString: item.color) ?? DS.accent)
                            .frame(width: 8, height: 8)
                        Toggle(isOn: Binding(
                            get: { item.shown },
                            set: { google.setCalendarAsync(connectionId: connection.id, calendarId: item.id, shown: $0) }
                        )) {
                            HStack(spacing: 6) {
                                Text(item.name).lineLimit(1)
                                if item.primary {
                                    Text("Primary")
                                        .font(.ds(11, .medium))
                                        .foregroundStyle(DS.text3)
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(Capsule().fill(DS.surface2))
                                }
                            }
                        }
                        .toggleStyle(DSToggleStyle())
                    }
                    .frame(minHeight: 32)
                }
            } else if google.calendarsLoading.contains(connection.id) {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("Loading calendars…")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                .frame(height: 28)
            } else if connection.needsReauth {
                Text("Calendars appear after the sign-in.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
        }
        .task(id: connection.id) {
            if google.calendars[connection.id] == nil, !connection.needsReauth {
                await google.loadCalendars(for: connection.id)
            }
        }
    }

    // MARK: - This phone's calendars (EventKit)

    private var calendarCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                ConnectorGlyph(symbol: "calendar")
                VStack(alignment: .leading, spacing: 2) {
                    Text("This phone's calendars")
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    Text(calendarSubtitle)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 4)
                calendarChip
            }
            calendarAction
            if calendar.access == .granted {
                calendarList
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private var calendarSubtitle: String {
        switch calendar.access {
        case .granted:
            let shown = calendar.calendars.filter(calendar.isCalendarShown).count
            return shown == calendar.calendars.count
                ? "\(calendar.calendars.count) calendars · next 7 days on the home page"
                : "\(shown) of \(calendar.calendars.count) calendars · next 7 days on the home page"
        case .notAsked: return "The accounts in Settings › Apps › Calendar, on this phone only."
        case .denied: return "Calendar access is off for Notes AI in Settings."
        case .unavailable: return "Not available in this build."
        }
    }

    @ViewBuilder
    private var calendarChip: some View {
        switch calendar.access {
        case .granted: DSChip(text: "Connected", tint: DS.ok, soft: DS.okSoft)
        case .notAsked: DSChip(text: "Not connected", tint: DS.muted, soft: DS.surface2)
        case .denied: DSChip(text: "Off", tint: DS.warn, soft: DS.warnSoft)
        case .unavailable: DSChip(text: "Unavailable", tint: DS.muted, soft: DS.surface2)
        }
    }

    @ViewBuilder
    private var calendarAction: some View {
        switch calendar.access {
        case .notAsked:
            Button("Connect") { Task { await calendar.requestAccess() } }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 36, fill: true))
        case .denied:
            Button("Open Settings") { open(UIApplication.openSettingsURLString) }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 36, fill: true))
        case .granted, .unavailable:
            EmptyView()
        }
    }

    private var calendarList: some View {
        VStack(alignment: .leading, spacing: 4) {
            DSDivider()
            if calendar.calendars.isEmpty {
                Text("No calendars yet — add an account in Settings › Apps › Calendar.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .padding(.top, 8)
            }
            ForEach(sources, id: \.self) { source in
                Text(source)
                    .font(.dsLabel)
                    .tracking(0.6)
                    .foregroundStyle(DS.muted)
                    .padding(.top, 10)
                    .padding(.bottom, 2)
                ForEach(calendar.calendars.filter { $0.source == source }) { item in
                    HStack(spacing: 8) {
                        Circle()
                            .fill(item.color.map { Color(cgColor: $0) } ?? DS.accent)
                            .frame(width: 8, height: 8)
                        Toggle(item.title, isOn: Binding(
                            get: { calendar.isCalendarShown(item) },
                            set: { calendar.setCalendar(item.id, shown: $0) }
                        ))
                        .toggleStyle(DSToggleStyle())
                    }
                    .frame(minHeight: 32)
                }
            }
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "plus.circle")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(DS.accentText)
                    .padding(.top, 2)
                Text("Google or Outlook calendar missing? Add the account in Settings › Apps › Calendar › Accounts; it shows up here.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.text3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.top, 10)
        }
    }

    private var sources: [String] {
        var seen: [String] = []
        for item in calendar.calendars where !seen.contains(item.source) { seen.append(item.source) }
        return seen
    }

    // MARK: - MCP connectors

    private var connectorsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                DSLabel("Connectors")
                Spacer()
                DSMenu(items: presetItems) {
                    HStack(spacing: 5) {
                        Image(systemName: "plus")
                            .font(.system(size: 11, weight: .semibold))
                        Text("Add")
                            .font(.ds(13.5, .medium))
                    }
                    .foregroundStyle(DS.text1)
                    .padding(.horizontal, 12)
                    .frame(height: 32)
                    .background(
                        RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                            .fill(DS.surface2)
                    )
                    .contentShape(Rectangle())
                }
            }
            if store.connectors.isEmpty {
                Text("Connect the tools your notes should reach — your CRM, wiki or tracker — through their MCP servers. Sign-ins stay in this phone's Keychain.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(store.connectors) { connector in
                DSDivider()
                ConnectorRow(
                    connector: connector,
                    busy: store.busy.contains(connector.id),
                    connect: { Task { await store.connect(connector.id) } },
                    menu: { menuItems(for: connector) })
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func presetItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [.header("Add a connector")]
        for preset in ConnectorPreset.all {
            if preset.id == "custom" { items.append(.separator) }
            items.append(.item(preset.name, symbol: preset.symbol) { add(preset) })
        }
        return items
    }

    private func add(_ preset: ConnectorPreset) {
        let connector = store.add(preset: preset)
        if preset.id == "custom" {
            editing = connector
        } else {
            Task { await store.connect(connector.id) }
        }
    }

    private func menuItems(for connector: Connector) -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Edit…", symbol: "pencil") { editing = connector },
            .item("Reconnect", symbol: "arrow.clockwise") { Task { await store.connect(connector.id) } },
        ]
        if !connector.toolNames.isEmpty {
            items.append(.item("Copy tool list", symbol: "doc.on.doc") {
                copyToPasteboard(connector.toolNames.joined(separator: "\n"))
            })
        }
        items.append(.separator)
        if case .connected = connector.status {
            items.append(.item("Disconnect", symbol: "xmark.circle") { store.disconnect(connector.id) })
        }
        items.append(.item("Remove", symbol: "trash", danger: true) { pendingRemoval = connector })
        return items
    }

    private func open(_ string: String) {
        if let url = URL(string: string) { UIApplication.shared.open(url) }
    }
}

// MARK: - Row

private struct ConnectorRow: View {
    let connector: Connector
    let busy: Bool
    let connect: () -> Void
    let menu: () -> [DSMenuItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                ConnectorGlyph(symbol: connector.symbol)
                VStack(alignment: .leading, spacing: 2) {
                    Text(connector.name.isEmpty ? "Untitled" : connector.name)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.dsMeta)
                        .foregroundStyle(subtitleColor)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 4)
                chip
                DSMenu(dim: true, items: menu)
            }
            action
        }
        .padding(.vertical, 4)
    }

    private var subtitle: String {
        switch connector.status {
        case .connected(let tools, let server):
            return "\(server) · \(tools) tool\(tools == 1 ? "" : "s")"
        case .failed(let why): return why
        case .connecting: return "Connecting…"
        case .needsSignIn: return "Sign in to connect \(connector.host)."
        case .notConnected: return connector.url.isEmpty ? "No server URL yet." : connector.host
        }
    }

    private var subtitleColor: Color {
        if case .failed = connector.status { return DS.dangerText }
        return DS.muted
    }

    @ViewBuilder
    private var chip: some View {
        switch connector.status {
        case .connected: DSChip(text: "Connected", tint: DS.ok, soft: DS.okSoft)
        case .connecting: DSChip(text: "Connecting", tint: DS.info, soft: DS.infoSoft, dot: true)
        case .needsSignIn: DSChip(text: "Sign in", tint: DS.warn, soft: DS.warnSoft)
        case .failed: DSChip(text: "Failed", tint: DS.danger, soft: DS.dangerSoft)
        case .notConnected: EmptyView()
        }
    }

    @ViewBuilder
    private var action: some View {
        if busy {
            HStack { Spacer(); ProgressView().controlSize(.small); Spacer() }
                .frame(height: 36)
        } else {
            switch connector.status {
            case .connected:
                EmptyView()
            case .needsSignIn:
                Button("Sign in", action: connect)
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 36, fill: true))
            case .failed:
                Button("Retry", action: connect)
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 36, fill: true))
            case .notConnected, .connecting:
                Button("Connect", action: connect)
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 36, fill: true))
            }
        }
    }
}

private struct ConnectorGlyph: View {
    let symbol: String

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(DS.accentText)
            .frame(width: 32, height: 32)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(DS.accentSoft)
            )
    }
}

// MARK: - Sheet chrome

/// A sheet with a title bar, Cancel / primary buttons and the paper ground.
private struct SheetFrame<Content: View>: View {
    let title: String
    let primaryTitle: String
    let primaryEnabled: Bool
    let busy: Bool
    let cancel: () -> Void
    let primary: () -> Void
    @ViewBuilder let content: () -> Content

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    content()
                }
                .padding(.horizontal, DS.gutter)
                .padding(.vertical, 14)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(DS.bg)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: cancel).disabled(busy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(primaryTitle, action: primary)
                        .font(.ds(15, .semibold))
                        .disabled(!primaryEnabled || busy)
                }
            }
        }
        .tint(DS.accentText)
        .presentationDetents([.medium, .large])
    }
}

// MARK: - Calendar link sheet (0020)

/// Paste a calendar's private iCal address. The server fetches it before
/// answering, so a wrong link fails right here with a readable message.
/// Shared by the Connectors page and the home page's Coming up card.
struct CalendarLinkSheet: View {
    @ObservedObject var google: GoogleCalendarService
    let onClose: () -> Void

    @State private var url = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        SheetFrame(title: "Add a calendar link", primaryTitle: busy ? "Checking…" : "Add",
                   primaryEnabled: isValid, busy: busy, cancel: onClose, primary: add) {
            Text("Paste the calendar's private iCal address. No Google sign-in needed; the events show here and in the web app.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 5) {
                Text("Calendar address")
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text3)
                DSTextField(placeholder: "https://calendar.google.com/calendar/ical/…/basic.ics", text: $url, mono: true)
                    .keyboardType(.URL)
            }
            Text("Google Calendar: Settings → your calendar → Integrate calendar → “Secret address in iCal format”. Published Outlook and iCloud calendar links work too.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let error {
                Text(error)
                    .font(.dsMeta)
                    .foregroundStyle(DS.dangerText)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var isValid: Bool {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return trimmed.hasPrefix("https://") || trimmed.hasPrefix("webcal://") || trimmed.hasPrefix("http://")
    }

    private func add() {
        guard isValid, !busy else { return }
        busy = true
        error = nil
        Task {
            if let message = await google.addLink(url: url) {
                error = message
            } else {
                onClose()
            }
            busy = false
        }
    }
}

// MARK: - Editor

/// Name, server URL, how to authenticate. A pasted token goes straight
/// to the Keychain and is never shown again.
private struct ConnectorEditor: View {
    let connector: Connector
    @ObservedObject var store: ConnectorStore
    let onClose: () -> Void

    @State private var name: String
    @State private var url: String
    @State private var auth: Connector.Auth
    @State private var token = ""
    @State private var clientId: String
    @State private var clientSecret = ""

    init(connector: Connector, store: ConnectorStore, onClose: @escaping () -> Void) {
        self.connector = connector
        self.store = store
        self.onClose = onClose
        _name = State(initialValue: connector.name)
        _url = State(initialValue: connector.url)
        _auth = State(initialValue: connector.auth)
        _clientId = State(initialValue: connector.clientId)
    }

    var body: some View {
        SheetFrame(title: connector.url.isEmpty ? "New connector" : "Edit connector",
                   primaryTitle: "Connect", primaryEnabled: isValid, busy: false,
                   cancel: {
                       // A freshly added custom connector with no URL is noise.
                       if connector.url.isEmpty, url.trimmingCharacters(in: .whitespaces).isEmpty {
                           store.remove(connector.id)
                       }
                       onClose()
                   },
                   primary: {
                       store.update(connector.id, name: name, url: url, auth: auth,
                                    token: token.isEmpty ? nil : token,
                                    clientId: auth == .oauth ? clientId : "",
                                    clientSecret: clientSecret.isEmpty ? nil : clientSecret)
                       onClose()
                       Task { await store.connect(connector.id) }
                   }) {
            field("Name") { DSTextField(placeholder: "HubSpot", text: $name) }
            field("Server URL") {
                DSTextField(placeholder: "https://…/mcp", text: $url, mono: true)
                    .keyboardType(.URL)
            }
            field("Sign in with") {
                DSSelect(options: [
                    .init(value: .oauth, label: "Browser sign-in", symbol: "person.badge.key", hint: "OAuth"),
                    .init(value: .token, label: "Access token", symbol: "key"),
                    .init(value: .none, label: "No sign-in", symbol: "lock.open"),
                ], selection: $auth)
            }
            if auth == .token {
                field("Token") {
                    DSTextField(placeholder: hasStoredToken ? "•••••••• (kept)" : "Paste the token",
                                text: $token, secure: true)
                }
                Text("A private-app token or API key, sent as a bearer token. Stored in this phone's Keychain.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            } else if auth == .oauth {
                Text("The server's own sign-in page opens in a browser sheet; the app registers itself and keeps the token in the Keychain.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                DSDivider()
                Text("Some servers (HubSpot) do not register apps themselves. Create an app on their side with this redirect URL and paste its credentials:")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 6) {
                    Text(MCPOAuth.redirectURI)
                        .font(.dsMono(12.5))
                        .foregroundStyle(DS.text2)
                        .textSelection(.enabled)
                    Button {
                        copyToPasteboard(MCPOAuth.redirectURI)
                    } label: {
                        Image(systemName: "doc.on.doc").font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(DS.muted)
                    .accessibilityLabel("Copy")
                }
                field("Client ID (optional)") {
                    DSTextField(placeholder: "From the server's app settings", text: $clientId, mono: true)
                }
                field("Client secret (optional)") {
                    DSTextField(placeholder: hasStoredClientSecret ? "•••••••• (kept)" : "If the app has one",
                                text: $clientSecret, secure: true)
                }
            }
        }
    }

    private var hasStoredToken: Bool { store.storedToken(for: connector.id) != nil }
    private var hasStoredClientSecret: Bool { store.storedClientSecret(for: connector.id) != nil }

    private var isValid: Bool {
        guard let parsed = URL(string: url.trimmingCharacters(in: .whitespaces)), parsed.host() != nil else { return false }
        if auth == .token, token.isEmpty, !hasStoredToken { return false }
        return true
    }

    private func field(_ label: String, @ViewBuilder control: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.ds(13, .medium))
                .foregroundStyle(DS.text3)
            control()
        }
    }
}
