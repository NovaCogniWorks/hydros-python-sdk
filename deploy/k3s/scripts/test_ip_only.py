"""IP-only live deployment regression checks; no cluster mutations."""
import json
import unittest
import live_deploy as deploy


class IpOnlyTest(unittest.TestCase):
    def metadata(self):
        values = {"appEnv": "on-premises", "dnsMode": "ip-only", "runtimeScheme": "https",
                  "hostname": "192.0.2.10", "httpGatewayTlsSecretName": "ip-tls"}
        for index, key in enumerate(("portal", "site", "api", "playground", "mcp")):
            values[key + "Host"] = f"192.0.2.10:{30481 + index}"
        return values

    def test_tls_ip_endpoints_and_route(self):
        env = deploy.standard_public_entrypoint_env(self.metadata())
        self.assertEqual(env["HYDROS_COOKIE_DOMAIN"], "")
        self.assertEqual(env["HYDROS_PORTAL_ORIGIN"], "https://192.0.2.10:30481")
        env["KUBE_NAMESPACE"] = "hydros"
        content = ("apiVersion: v1\nkind: Service\nmetadata:\n  name: " + deploy.APP_NAME
                   + "\nspec:\n  type: ClusterIP\n  ports:\n    - name: http\n      port: 8080\n")
        route = deploy.render_ip_only_route(content, env)
        if env["HYDROS_IP_ENTRYPOINT"]:
            document = json.loads(route)
            self.assertEqual(document["spec"]["tls"]["secretName"], "ip-tls")
            self.assertEqual(document["spec"]["routes"][0]["services"][0]["port"], 8080)
            self.assertEqual(document["spec"]["routes"][0]["match"], "PathPrefix(`/`)")
        else:
            self.assertEqual(route, "")

    def test_http_foreign_host_and_duplicate_port_rejected(self):
        for change in ({"runtimeScheme": "http"}, {"portalHost": "other.example:30481"},
                       {"siteHost": "192.0.2.10:30481"}):
            with self.subTest(change=change), self.assertRaises(SystemExit):
                deploy.standard_public_entrypoint_env(self.metadata() | change)


if __name__ == "__main__":
    unittest.main()
