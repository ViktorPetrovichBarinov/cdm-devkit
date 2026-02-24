import * as path from "path";
import * as vscode from "vscode";
import { LanguageClient, LanguageClientOptions, ServerOptions } from "vscode-languageclient/node";

let client: LanguageClient;

export async function activate(context: vscode.ExtensionContext) {
    console.log("Process PATH:", process.env.PATH);

    // Путь к серверу Python
    const serverScript = context.asAbsolutePath(
        path.join("..", "server", "src", "server.py") // путь относительно корня расширения
    );

    const pythonPath = "Z:/Repos/ext/.venv/Scripts/python.exe";
    // запуск python
    const serverOptions: ServerOptions = {
        command: "Z:/Repos/ext/.venv/Scripts/python.exe",
        args: [serverScript],
        options: { cwd: path.dirname(serverScript) },
    };

    // клиент
    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "*" }],
        outputChannel: vscode.window.createOutputChannel("CDM16 LSP"),
    };

    // Создаём и запускаем клиент
    client = new LanguageClient(
        "cdm16-lsp",                    // ID клиента
        "CDM16 Language Server",        // Имя для логов
        serverOptions,
        clientOptions
    );

    // Запускаем клиента
    client.start();

    // Добавляем клиента в подписки, чтобы VSCode мог корректно его остановить
    context.subscriptions.push(client);
    vscode.window.showInformationMessage("CDM16 LSP client started!");
}

export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
    }
}
